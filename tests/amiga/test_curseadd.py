"""The Curse ADD CHARACTER driver: the host copy, the guarded route and its fail-closed paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

import pytest

from automap import gamedisks
from goldbox import amiga_adf
from tools.amiga import curseadd
from tools.amiga.winuaesession import RouteError
from tools.registry import specimens


def _record(name: str, control: int = 0, status: int = 0, kind: int = 0) -> bytes:
    raw = bytearray(curseadd.AMIGA_POR_RECORD_SIZE)
    raw[:len(name)] = name.encode()
    raw[0x85], raw[0x10E], raw[0xA1], raw[0x11D] = control, status, kind, 9
    return bytes(raw)


def _pool_disk(files: dict[str, bytes]) -> amiga_adf.AmigaDisk:
    disk = amiga_adf.AmigaDisk.blank("poolsave")
    disk.make_dir("save")
    for name, data in files.items():
        disk.write_file(f"save/{name}", data)
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


def test_copy_records_a_character_with_no_effects_file():
    target = _curse_disk()
    rows = curseadd.copy_characters(_pool_disk({"GEN.cha": _record("GEN", 0xB2)}), target, ["GEN"])
    assert rows[0]["spc"] is None
    assert target.read_file("SAVE/GEN.cha")[0x85] == 0xB2


@pytest.mark.parametrize("case", ["listed_cha", "listed_sav", "wrong_size", "other_name",
                                  "missing", "duplicate_stem", "none"])
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
    elif case == "none":
        names = []
    target = _curse_disk(present)
    before = target.to_bytes()
    with pytest.raises(RouteError):
        curseadd.copy_characters(_pool_disk(files), target, names)
    if case not in ("wrong_size", "other_name"):
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

    def grab(self, label, raw, crop, timeout):
        self.current = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        self.clock.now += 1
        return True

    def press(self, holder, key, timeout):
        self.keys.append(key)


class FakeGuards:
    def __init__(self, guest):
        self.guest = guest

    def __contains__(self, state):
        return state in curseadd.KNOWN

    def __call__(self, state, crop):
        return state == self.guest.current


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


def test_boot_stops_after_the_escape_cap(tmp_path):
    screens, guest = _screens(tmp_path, ["front_end"])
    with pytest.raises(RouteError, match="ESCs"):
        screens.to_party_menu(3000)
    assert guest.keys == ["ESC"] * curseadd.BOOT_ESCAPES


def _manifest(tmp_path, stems, names=("GALAIN", "HOLLAND")):
    disk = _curse_disk()
    for stem in stems:
        disk.write_file(f"SAVE/{stem}.cha", _record(stem, 0xB2 if stem == "GEN" else 0))
    save = tmp_path / "save.adf"
    disk.save(save)
    return {"title": "curse", "disks": {"save": {"path": str(save)}},
            "add": {"load": "A", "save": "D", "load_names": list(names),
                    "copies": [{"stem": stem, "cha": {"target": f"SAVE/{stem}.cha"}}
                               for stem in stems]}}


ROUTE_ONE = [None, "intro", "front_end", "title", "load_picker", None, "loaded_menu",
             "add_from", "add_picker", "add_picker", "loaded_menu", "sheet", "loaded_menu",
             "save_picker", "saving", "loaded_menu", "loaded_menu"]


def test_drive_adds_views_and_saves_one_character(tmp_path):
    screens, guest = _screens(tmp_path, ROUTE_ONE)
    manifest = _manifest(tmp_path, ["ROSALIND"])
    live = [{"name": n, "control": 0, "status": 0, "type": 0}
            for n in ("GALAIN", "HOLLAND", "ROSALIND")]
    found = curseadd.drive(screens, manifest, "holder", lambda holder: live)
    assert guest.keys == ["ESC", "ESC", "L", "A", "A", "P", "A", "E", "V", "E", "S", "D"]
    assert found["live_fields"]["ROSALIND"]["control"] == {"cha": 0, "live": 0, "equal": True}


def test_drive_adds_two_and_takes_the_picker_closing_itself(tmp_path):
    script = [None, "title", "load_picker", "loaded_menu", "add_from", "add_picker",
              "add_picker", "loaded_menu", "sheet", "loaded_menu", "sheet", "loaded_menu",
              "save_picker", "loaded_menu", "loaded_menu"]
    screens, guest = _screens(tmp_path, script)
    manifest = _manifest(tmp_path, ["ROSALIND", "GEN"])

    def unreadable(holder):
        raise RouteError("the party list does not read")

    found = curseadd.drive(screens, manifest, "holder", unreadable)
    assert guest.keys == ["L", "A", "A", "P", "A", "NP1", "A", "V", "E", "NP7", "V", "E",
                          "S", "D"]
    assert "the party list does not read" in found["live_error"]


def test_drive_stops_when_the_picker_closes_early(tmp_path):
    script = [None, "title", "load_picker", "loaded_menu", "add_from", "add_picker",
              "loaded_menu"]
    screens, guest = _screens(tmp_path, script)
    with pytest.raises(RouteError, match="closed after 1 of 2"):
        curseadd.drive(screens, _manifest(tmp_path, ["ROSALIND", "GEN"]), "holder",
                       lambda holder: [])
    assert "S" not in guest.keys


def test_drive_stops_before_saving_when_the_live_party_differs(tmp_path):
    screens, guest = _screens(tmp_path, ROUTE_ONE)
    live = [{"name": n, "control": 0, "status": 0, "type": 0} for n in ("GALAIN", "OTHER")]
    with pytest.raises(RouteError, match="party after ADD"):
        curseadd.drive(screens, _manifest(tmp_path, ["ROSALIND"]), "holder", lambda h: live)
    assert "S" not in guest.keys


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


@pytest.mark.parametrize("problem", ["out_exists", "not_staged", "hash", "slot_taken"])
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
    else:
        monkeypatch.setattr(curseadd, "slot_letters", lambda disk: ["A", "D"])
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
    manifest = {"add": {"load_names": ["GALAIN"]}}
    found = {"verify": [], "kept": ["GALAIN"], "names": ["GALAIN", "GEN"], "members": {
        "GEN": {"seated": 1, "fields": {
            "control": {"cha": 0xB2, "curse": 0, "equal": False},
            "status": {"cha": 0, "curse": 0, "equal": True},
            "type": {"cha": 0, "curse": 0, "equal": True}}},
        "ROSALIND": {"seated": 0}}}
    problems = curseadd.verdict(found, manifest)
    assert any("GEN control" in p for p in problems)
    assert any("ROSALIND" in p for p in problems)
    assert curseadd.verdict({**found, "members": {}}, manifest) == []


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
    path = curseadd.stage(prep, source, ["ROSALIND", "GENHEERIS"], tmp_path / "out")
    staged = json.loads(path.read_text())
    assert staged["add"]["load_names"] == ["GALAIN", "HOLLAND", "IILANDA", "SUNDRA"]
    assert [row["stem"] for row in staged["add"]["copies"]] == ["ROSALIND", "GENHEERIS"]
    disk = amiga_adf.AmigaDisk.open(staged["disks"]["save"]["path"])
    assert disk.read_file("SAVE/GENHEERIS.cha")[0x85] == 0xB2
    assert staged["add"]["copies"][1]["spc"] is None
    assert disk.verify() == []
    assert digest(source) == source_hash and digest(save) == staged["prepared_from"]["save_sha256"]
    with pytest.raises(RouteError, match="already exists"):
        curseadd.stage(prep, source, ["ROSALIND"], tmp_path / "out")
    with pytest.raises(RouteError, match="player members"):
        curseadd.stage(prep, source, ["ROSALIND", "CONJURER", "ADDERLY"], tmp_path / "out2",
                       load="A")
