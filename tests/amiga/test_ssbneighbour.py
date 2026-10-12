"""The guarded neighbour wrapper must stop and clean up on an unknown load screen."""

import argparse
import contextlib
import hashlib
import json
import pathlib
import subprocess

import pytest
from PIL import Image

from automap import gamedisks
from goldbox.geo import EAST, SOLID, WEST, Geo
from tools.amiga import guardmaps
from tools.amiga import ssbneighbour as neighbour
from tools.amiga.screens import PixelGuards, box_digests, canonical_file, guard_rule
from tools.amiga.winuaesession import RouteError, ShotTimedOut
from tools.records.geoports import every_port


@pytest.mark.parametrize("missing", ["registry", "reader", "template", "df0_unreadable",
                                     "df0_empty"])
def test_journal_dependencies_stop_before_output_or_guest(tmp_path, monkeypatch, missing):
    inputs = {}
    for key in ("boot_source", "disk_b_source", "substitute", "published_df1", "df0", "df1"):
        disk = tmp_path / f"{key}.adf"
        disk.write_bytes(f"synthetic {key}".encode())
        inputs[key] = {"path": str(disk), "sha256": hashlib.sha256(disk.read_bytes()).hexdigest()}
    manifest = {**inputs, "disks": {key: inputs[key] for key in ("df0", "df1")},
                "registered": {key: inputs[key] for key in ("boot_source", "disk_b_source",
                                                              "substitute")}
                | {"published": inputs["published_df1"]},
                "state_a": {"area": 16, "x": 3, "y": 7, "facing": 2},
                "names_a": [f"Member {n}" for n in range(6)],
                "mode": "substitute_title", "title": "ssb", "loaded_letter": "D",
                "slot_letter": "D"}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    events = []
    if missing == "registry":
        monkeypatch.setattr(gamedisks, "REGISTRY", tmp_path / "missing.yaml")
        monkeypatch.setenv("WISH_CODEWHEEL", str(tmp_path / "override"))
    else:
        monkeypatch.setattr(gamedisks, "names", lambda: events.append("registry") or ["codewheel"])

    def reader(interpreter):
        events.append("reader")
        assert interpreter == neighbour.sys.executable
        if missing in ("reader", "template"):
            raise RouteError(f"private {missing} is unavailable")

    def tables(adf):
        events.append("tables")
        assert adf == pathlib.Path(inputs["df0"]["path"])
        if missing == "df0_unreadable":
            raise OSError("unreadable prepared disk")
        return [] if missing == "df0_empty" else [object()]

    monkeypatch.setattr(neighbour.route_silver_blades, "journal_preflight", reader)
    monkeypatch.setattr(neighbour.amigabladesjournal, "tables", tables)
    monkeypatch.setattr(neighbour.amigabladesjournal, "answer",
                        lambda *a, **k: pytest.fail("Journal answer was called"))
    monkeypatch.setattr(neighbour.acceptance, "boot_lane",
                        lambda *a, **k: pytest.fail("Lane was claimed"))

    class Guest:
        def _run(self, *a, **k):
            pytest.fail("SSH mute was queried")

        def press(self, *a, **k):
            pytest.fail("A key was sent")

    out = tmp_path / "result"
    args = argparse.Namespace(manifest=path, holder="fake-holder", out=out,
                              budget=3600, wait_lane=0, retry_of=None)
    with pytest.raises(RouteError, match="journal prerequisites are unavailable before boot"):
        neighbour.run(args, guest=Guest())
    assert not out.exists()
    assert events == ([] if missing == "registry" else ["registry", "reader"]
                      if missing in ("reader", "template") else ["registry", "reader", "tables"])


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("during", ["reader", "tables"])
def test_expired_journal_preflight_stops_before_output_or_guest(tmp_path, monkeypatch,
                                                                retry, during):
    inputs = {}
    for key in ("boot_source", "disk_b_source", "substitute", "published_df1", "df0", "df1"):
        disk = tmp_path / f"{key}.adf"
        disk.write_bytes(f"synthetic {key}".encode())
        inputs[key] = {"path": str(disk), "sha256": hashlib.sha256(disk.read_bytes()).hexdigest()}
    manifest = {**inputs, "disks": {key: inputs[key] for key in ("df0", "df1")},
                "registered": {key: inputs[key] for key in ("boot_source", "disk_b_source",
                                                              "substitute")}
                | {"published": inputs["published_df1"]},
                "state_a": {"area": 16, "x": 3, "y": 7, "facing": 2},
                "names_a": [f"Member {n}" for n in range(6)],
                "mode": "substitute_title", "title": "ssb", "loaded_letter": "D",
                "slot_letter": "D"}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    out = tmp_path / "result"
    old_receipt = None
    if retry:
        old_out = tmp_path / "previous"
        old_out.mkdir()
        old_receipt = old_out / "receipt.json"
        old_receipt.write_text(json.dumps({"success": False, "retryable": True,
            "retry_of": None, "manifest": str(path.resolve()), "holder": "fake-holder",
            "out": str(old_out.resolve()), "combined_deadline": 1005}))
    now = [1000]
    monkeypatch.setattr(neighbour.time, "time", lambda: now[0])
    monkeypatch.setattr(gamedisks, "names", lambda: ["codewheel"])

    def reader(interpreter):
        assert interpreter == neighbour.sys.executable
        if during == "reader":
            now[0] = 1006

    def tables(adf):
        assert adf == pathlib.Path(inputs["df0"]["path"])
        if during == "tables":
            now[0] = 1006
        return [object()]

    monkeypatch.setattr(neighbour.route_silver_blades, "journal_preflight", reader)
    monkeypatch.setattr(neighbour.amigabladesjournal, "tables", tables)
    monkeypatch.setattr(neighbour.amigabladesjournal, "answer",
                        lambda *a, **k: pytest.fail("Journal answer was called"))
    monkeypatch.setattr(neighbour.acceptance, "boot_lane",
                        lambda *a, **k: pytest.fail("Lane was claimed"))

    class Guest:
        def _run(self, *a, **k):
            pytest.fail("SSH mute was queried")

        def press(self, *a, **k):
            pytest.fail("A key was sent")

    args = argparse.Namespace(manifest=path, holder="fake-holder", out=out,
                              budget=5, wait_lane=0, retry_of=old_receipt)
    with pytest.raises(RouteError, match="the combined deadline expired"):
        neighbour.run(args, guest=Guest())
    assert not out.exists()
    if old_receipt is not None:
        assert not old_receipt.with_suffix(".retry-claimed").exists()


def test_journal_preflight_with_time_remaining_creates_no_output(tmp_path, monkeypatch):
    inputs = {}
    for key in ("boot_source", "disk_b_source", "substitute", "published_df1", "df0", "df1"):
        disk = tmp_path / f"{key}.adf"
        disk.write_bytes(f"synthetic {key}".encode())
        inputs[key] = {"path": str(disk), "sha256": hashlib.sha256(disk.read_bytes()).hexdigest()}
    manifest = {**inputs, "disks": {key: inputs[key] for key in ("df0", "df1")},
                "registered": {key: inputs[key] for key in ("boot_source", "disk_b_source",
                                                              "substitute")}
                | {"published": inputs["published_df1"]},
                "state_a": {"area": 16, "x": 3, "y": 7, "facing": 2},
                "names_a": [f"Member {n}" for n in range(6)],
                "mode": "substitute_title", "title": "ssb", "loaded_letter": "D",
                "slot_letter": "D"}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(neighbour.time, "time", lambda: 1000)
    monkeypatch.setattr(gamedisks, "names", lambda: ["codewheel"])
    monkeypatch.setattr(neighbour.route_silver_blades, "journal_preflight", lambda interpreter: None)
    monkeypatch.setattr(neighbour.amigabladesjournal, "tables", lambda adf: [object()])
    out = tmp_path / "result"
    prepared, deadline = neighbour.preflight(path, out, None, 5)
    assert prepared == manifest
    assert deadline == 1005
    assert not out.exists()


@pytest.mark.parametrize("unknown_picker,failure", [
    (False, None), (True, None), (False, "snapshot_lost"),
    (False, "snapshot_before_create"), (False, "shot_timeout"),
    (False, "child_timeout"),
])
def test_one_lane_proves_both_neighbour_legs_and_cleans_up(tmp_path, monkeypatch,
                                                             unknown_picker, failure, well_case=None):
    source = tmp_path / "inputs"
    source.mkdir()
    inputs = {}
    for key in ("boot_source", "disk_b_source", "substitute", "published_df1", "df0", "df1"):
        path = source / f"{key}.adf"
        path.write_bytes((key + " synthetic disk").encode())
        inputs[key] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {**inputs, "disks": {key: inputs[key] for key in ("df0", "df1")},
                "registered": {key: inputs[key] for key in ("boot_source", "disk_b_source",
                                                              "substitute")}
                | {"published": inputs["published_df1"]},
                "state_a": {"area": 16, "x": 3, "y": 7, "facing": 2},
                "names_a": [f"Member {n}" for n in range(6)],
                "mode": "substitute_title", "title": "ssb", "loaded_letter": "D",
                "slot_letter": "D"}
    original = tmp_path / "original.json"
    original.write_text(json.dumps(manifest))
    names = manifest["names_a"]
    events = []
    current = {"area": 16, "square": (3, 7, 2), "names": names, "variables": {},
               "target": object()}

    class Guest:
        def _run(self, *args, **kwargs):
            events.append(("mute", *args))
            return '{"muted": true}'

        def silence(self, proof):
            return proof.exists()

        def grab(self, state, raw, crop, timeout):
            if failure == "shot_timeout":
                raise ShotTimedOut("winvm ssh exceeded its 20.0s limit")
            raw.write_bytes(b"synthetic raw")
            crop.write_bytes(b"synthetic cropped " + (well_case or "normal").encode())
            return True

        def press(self, holder, key, timeout):
            events.append(("press", key))
            if key == "RET" and well_case == "wrong_after":
                current["square"] = (3, 3, 1)

        def snapshot(self, name, holder):
            if failure == "snapshot_before_create":
                raise RouteError("snapshot creation stopped")
            events.append(("snapshot", name))
            if failure == "snapshot_lost":
                raise RouteError("snapshot response lost")

        def restore(self, name, holder):
            events.append(("restore", name))
            current.update(area=16, square=(3, 7, 2), variables={})

        def discard(self, name, holder):
            events.append(("discard", name))

        def answer_io(self, holder):
            pytest.fail("No journal screen was presented")

    class Guards:
        rules = dict.fromkeys(("title", "party_menu", "load_picker", "loaded_menu",
                                "journal", "world", "well_entry_continue",
                                "temple_entry_continue", "temple_clear_world"))

        def __contains__(self, name):
            return name in self.rules

        def __call__(self, state, crop):
            if state == "well_entry_continue":
                return well_case not in ("bar_only", "changed_story")
            if state == "world" and well_case == "shut_world" and ("RET",) in [
                    event[1:] for event in events if event[0] == "press"]:
                return True
            return state != "journal" and not (unknown_picker and state == "load_picker")

    class State:
        def load(self):
            return {"on": False, "rows": []}

    class Switch:
        def __init__(self, target):
            pass

        def on(self):
            events.append(("switch", "on"))
            return {"action": "on"}

        def keys(self, keys):
            events.append(("switch", *keys))
            assert keys in (["NP6"], ["NP8"])
            x, y, facing = current["square"]
            if keys == ["NP6"]:
                current["square"] = (x, y, (facing + 1) % 4)
            elif current["area"] == 52:
                if facing == EAST:
                    current["square"] = (3, 15, EAST)
            elif facing == WEST:
                current["square"] = (x - 1, y, facing)
            return {"pressed": keys}

        def off(self):
            events.append(("switch", "off"))
            return {"action": "off"}

    def boot(local, prepared, title, **kwargs):
        events.append(("boot", str(local)))
        assert prepared["disks"]["df0"]["path"] != inputs["df0"]["path"]
        return {"holder": kwargs["holder"]}

    def halt(guest, holder, **kwargs):
        events.extend((("stop", holder), ("fetch", holder), ("release", holder)))
        return {"fetched": {"df0": {}, "df1": {}}}

    def execute(run, disks, out, flags, start, end):
        events.append(("trip", start, end, tuple(flags), str(out), str(disks)))
        if failure == "child_timeout":
            raise RouteError("trip child exceeded its deadline: fake") from subprocess.TimeoutExpired(
                "fasttravelrun", 480)
        assert start == current["area"]
        positions = {33: (1, 1, 2), 52: (2, 15, 3), 82: (1, 11, 1), 81: (15, 6, 3)}
        if end == 33 and well_case in ("diagnostic_before", "diagnostic_after"):
            current.update(area=end, square=positions[end])
            summary = {"result": "idle", "settled": False, "areas_seen": [16, 33],
                       "arrival_keys": [], "arrival_answered": False,
                       "party_before": names, "party_after": names}
            output = json.dumps(summary) + "\n"
            output = ("Unexpected child diagnostic.\n" + output if well_case == "diagnostic_before"
                      else output + "Unexpected child diagnostic.\n")

            class Child:
                returncode = 1

                def communicate(self, timeout):
                    return output, neighbour.WELL_PENDING_STDERR

                def poll(self):
                    return self.returncode

            monkeypatch.setattr(neighbour.subprocess, "Popen", lambda *a, **k: Child())
            return neighbour.trip(run, disks, out, flags, start, end)
        out.mkdir()
        (out / "stdout.txt").write_text(f"{start} -> {end}\n")
        (out / "stderr.txt").write_text("")
        current.update(area=end, square=positions[end])
        if end == 33 and well_case == "wrong_prompt":
            current["square"] = (3, 3, 1)
        if end == 52:
            current["variables"] = {"4C62": 5, "4C2A": 0}
        if end == 81:
            current["variables"] = dict.fromkeys(("4CFD", "4C6C"), 64) | dict.fromkeys(("4CFE", "4C6D"), 85)
        return {"command": flags, "pending_well": end == 33 and well_case is not None,
                "result": {"areas_seen": [start, end], "result": "idle",
                                           "settled": not (end == 33 and well_case is not None), "arrival_keys": [],
                                           "party_before": names, "party_after": names},
                "stdout": str(out / "stdout.txt"), "stderr": str(out / "stderr.txt")}

    monkeypatch.setattr(neighbour.route_silver_blades, "title_for_substitute", lambda m: object())
    monkeypatch.setattr(gamedisks, "names", lambda: ["codewheel"])
    monkeypatch.setattr(neighbour.route_silver_blades, "journal_preflight", lambda interpreter: None)
    monkeypatch.setattr(neighbour.amigabladesjournal, "tables", lambda adf: [object()])
    monkeypatch.setattr(neighbour.acceptance, "boot_lane", boot)
    monkeypatch.setattr(neighbour.acceptance, "halt_lane", halt)
    monkeypatch.setattr(neighbour.noencounters, "WinuaeState", lambda path: State())
    monkeypatch.setattr(neighbour.noencounters, "winuae_state_path", lambda holder: tmp_path / "gate.json")
    monkeypatch.setattr(neighbour.amigatrip, "gate", lambda target, row: well_case != "shut_world")
    args = argparse.Namespace(manifest=original, holder="fake-holder", out=tmp_path / "result",
                              budget=3600, wait_lane=0, retry_of=None)
    options = dict(guest=Guest(), guards=Guards(), reader=lambda holder: current.copy(),
                   executor=execute, switch_factory=Switch)
    if unknown_picker or failure or well_case in ("bar_only", "changed_story", "wrong_prompt",
                                                  "wrong_after", "shut_world", "diagnostic_before",
                                                  "diagnostic_after"):
        reason = "load_picker" if unknown_picker else {
            "snapshot_lost": "snapshot response lost",
            "snapshot_before_create": "snapshot creation stopped",
            "shot_timeout": "exceeded its",
            "child_timeout": "trip child exceeded its deadline",
        }[failure] if failure else {
            "bar_only": "well_entry_continue", "changed_story": "well_entry_continue",
            "wrong_prompt": "square in 33", "wrong_after": "square in 33",
            "shut_world": "world gate is still shut",
            "diagnostic_before": "one JSON object", "diagnostic_after": "one JSON object",
        }[well_case]
        try:
            with pytest.raises(RouteError, match=reason):
                neighbour.run(args, **options)
        finally:
            if well_case in ("diagnostic_before", "diagnostic_after"):
                assert ("press", "RET") not in events
    else:
        receipt = neighbour.run(args, **options)
        assert receipt["success"] is True
        assert [(v[1], v[2]) for v in events if v[0] == "trip"] == [
            (16, 33), (33, 52), (16, 82), (82, 81)]
        assert [v[3] for v in events if v[0] == "trip"] == [
            ("--to", "33"),
            ("--waypoint", "52,7,3,2", "--back", "--peek-var", "4C62,4C2A,4CFD,4CFE"),
            ("--to", "82"),
            ("--waypoint", "81,5,8,1", "--back", "--arrival-answer", "RET",
             "--peek-var", "4CFD,4CFE,4C6C,4C6D")]
        assert len({v[4] for v in events if v[0] == "trip"}) == 4
        assert len({v["stdout"] for v in receipt["trips"]}) == 4
        assert all((args.out / f"trip-{n}" / "stdout.txt").is_file() for n in range(1, 5))
        assert ("restore", "s0") in events
        assert receipt["reads"]["52"]["variables"]["4C62"] == 5
        assert receipt["reads"]["81"]["square"] == (15, 6, 3)
        assert receipt["reads"]["81-step"]["square"] == (14, 6, 3)
        assert [v[1] for v in events if v[0] == "switch"] == [
            "on", "NP6", "NP6", "NP8", "off", "on", "NP8", "off"]
        assert receipt["reads"]["52-step"]["square"] == (3, 15, EAST)
    assert [v[1] for v in events if v[0] == "press"] == (
        [] if failure == "shot_timeout" else
        ["P", "L"] if unknown_picker else ["P", "L", "D", "B"] +
        (["RET"] if well_case not in (None, "bar_only", "changed_story", "wrong_prompt",
                                     "diagnostic_before", "diagnostic_after") else []))
    if unknown_picker:
        assert not any(v[0] == "trip" for v in events)
    if well_case is not None:
        assert len([v for v in events if v[0] == "trip"]) == (
            4 if well_case == "pending" else 1)
        if well_case not in ("wrong_prompt", "bar_only", "changed_story", "diagnostic_before",
                             "diagnostic_after"):
            assert ("press", "RET") in events
            assert events.index(("trip", 16, 33, ("--to", "33"),
                                 str(args.out / "trip-1"), str(source))) < events.index(("press", "RET"))
        else:
            assert ("press", "RET") not in events
        if well_case in ("diagnostic_before", "diagnostic_after"):
            assert (args.out / "trip-1" / "stdout.txt").read_text().count("Unexpected child diagnostic.") == 1
            assert (args.out / "trip-1" / "stderr.txt").read_text() == neighbour.WELL_PENDING_STDERR
    if failure in ("snapshot_lost", "snapshot_before_create"):
        assert ("discard", "s0") in events
        assert not any(v[0] == "trip" for v in events)
    if failure == "snapshot_before_create":
        assert ("snapshot", "s0") not in events
    if failure == "snapshot_lost":
        assert ("snapshot", "s0") in events
    assert [v[0] for v in events if v[0] in {"stop", "fetch", "release"}] == [
        "stop", "fetch", "release"]
    assert all(hashlib.sha256((source / f"{key}.adf").read_bytes()).hexdigest() == inputs[key]["sha256"]
               for key in inputs)
    saved = json.loads((args.out / "receipt.json").read_text())
    assert saved["success"] is (not unknown_picker and failure is None and
                                well_case in (None, "pending"))
    assert saved["retryable"] is (failure == "shot_timeout")
    if failure in ("snapshot_lost", "snapshot_before_create"):
        assert saved["snapshots"] == ["s0"]
        assert {"discard": "s0"} in saved["cleanup"]
        assert saved["halt"]["fetched"] == {"df0": {}, "df1": {}}
    if failure == "child_timeout":
        assert any(item[0] == "trip" for item in events)
        assert {"discard": "s0"} in saved["cleanup"]
        assert saved["halt"]["fetched"] == {"df0": {}, "df1": {}}
    if unknown_picker:
        assert list((args.out / "screens").glob("*-load_picker-raw.png"))
    if well_case is not None:
        if well_case in ("wrong_prompt", "diagnostic_before", "diagnostic_after"):
            assert "well_prompt" not in saved["reads"]
        else:
            assert saved["reads"]["well_prompt"]["square"] == [1, 1, 2]
        assert {"discard": "s0"} in saved["cleanup"]
        assert saved["halt"]["fetched"] == {"df0": {}, "df1": {}}
        if well_case in ("bar_only", "changed_story"):
            assert list((args.out / "screens").glob("*-well_entry_continue-raw.png"))


@pytest.mark.parametrize("well_case", ["pending", "bar_only", "changed_story",
                                         "wrong_prompt", "wrong_after", "shut_world",
                                         "diagnostic_before", "diagnostic_after"])
def test_well_page_allows_only_one_guarded_return_before_the_next_leg(tmp_path, monkeypatch,
                                                                       well_case):
    test_one_lane_proves_both_neighbour_legs_and_cleans_up(tmp_path, monkeypatch, False, None,
                                                            well_case)


@pytest.mark.parametrize("change", [None, "stderr", "extra_error", "wrong_area", "wrong_names",
                                    "already_answered", "wrong_flags", "wrong_leg", "extra_row",
                                    "wrong_result", "empty_name", "wrong_code", "diagnostic_before",
                                    "diagnostic_after", "nonobject", "surrounding_whitespace"])
def test_child_only_admits_the_exact_pending_well_outcome(tmp_path, monkeypatch, change):
    names = [f"Member {n}" for n in range(6)]
    summary = {"result": "idle", "settled": False, "areas_seen": [16, 33],
               "arrival_keys": [], "arrival_answered": False,
               "party_before": names, "party_after": names.copy()}
    stderr = neighbour.WELL_PENDING_STDERR
    flags, start, end, code = ["--to", "33"], 16, 33, 1
    if change == "stderr":
        stderr = "Leg 1 never became ready.\n"
    elif change == "extra_error":
        stderr += "Another child error.\n"
    elif change == "wrong_area":
        summary["areas_seen"] = [16, 52]
    elif change == "wrong_names":
        summary["party_after"][-1] = "Different"
    elif change == "already_answered":
        summary["arrival_answered"] = True
    elif change == "wrong_flags":
        flags = ["--to", "33", "--arrival-answer", "RET"]
    elif change == "wrong_leg":
        start = 33
    elif change == "wrong_result":
        summary["result"] = "failed"
    elif change == "empty_name":
        summary["party_before"][-1] = summary["party_after"][-1] = ""
    elif change == "wrong_code":
        code = 2
    stdout = json.dumps(summary) + "\n"
    if change == "extra_row":
        stdout += json.dumps(summary) + "\n"
    elif change == "diagnostic_before":
        stdout = "Unexpected child diagnostic.\n" + stdout
    elif change == "diagnostic_after":
        stdout += "Unexpected child diagnostic.\n"
    elif change == "nonobject":
        stdout = json.dumps([summary]) + "\n"
    elif change == "surrounding_whitespace":
        stdout = " \n" + stdout + "\t\n"

    class Child:
        returncode = code

        def communicate(self, timeout):
            return stdout, stderr

        def poll(self):
            return self.returncode

    class Run:
        holder = "fake-holder"

        def left(self, cap):
            return cap

    monkeypatch.setattr(neighbour.subprocess, "Popen", lambda *a, **k: Child())
    out = tmp_path / "child"
    if change in (None, "surrounding_whitespace"):
        leg = neighbour.trip(Run(), tmp_path, out, flags, start, end)
        assert leg["pending_well"] is True
        assert leg["result"] == summary
    else:
        with pytest.raises(RouteError):
            neighbour.trip(Run(), tmp_path, out, flags, start, end)
    assert (out / "stdout.txt").read_text() == stdout
    assert (out / "stderr.txt").read_text() == stderr


@pytest.mark.parametrize("change", [None, "stderr", "wrong_flags", "wrong_code", "wrong_area",
                                     "wrong_names", "empty_name", "answered", "arrival_key",
                                     "wrong_result", "settled", "extra_row", "nonobject",
                                     "diagnostic_before", "diagnostic_after", "missing_outcomes",
                                     "empty_outcomes", "nonlist_outcomes", "nondict_outcome",
                                     "nonbool_ok", "failed_apply", "failed_continue"])
def test_child_only_admits_the_exact_pending_temple_outcome(tmp_path, monkeypatch, change):
    names = [f"Member {n}" for n in range(6)]
    summary = {"result": "idle", "settled": False, "areas_seen": [33, 52],
               "arrival_keys": [], "arrival_answered": False,
               "party_before": names, "party_after": names.copy(),
               "outcomes": [{"ok": True, "message": "applied"}]}
    flags = ["--waypoint", "52,7,3,2", "--back", "--peek-var", "4C62,4C2A,4CFD,4CFE"]
    stderr = ("Leg 1 (the trip) never became ready for Fast Travel.\n"
              "The leg reached area 52 and the game is still waiting on its screen; "
              "give its keys with --arrival-answer (repeat it for several screens).\n")
    code = 1
    if change == "stderr":
        stderr += "Unexpected error.\n"
    elif change == "wrong_flags":
        flags += ["--arrival-answer", "RET"]
    elif change == "wrong_code":
        code = 2
    elif change == "wrong_area":
        summary["areas_seen"] = [16, 52]
    elif change == "wrong_names":
        summary["party_after"][-1] = "Different"
    elif change == "empty_name":
        summary["party_before"][-1] = summary["party_after"][-1] = ""
    elif change == "answered":
        summary["arrival_answered"] = True
    elif change == "arrival_key":
        summary["arrival_keys"] = ["RET"]
    elif change == "wrong_result":
        summary["result"] = "failed"
    elif change == "settled":
        summary["settled"] = True
    elif change == "missing_outcomes":
        del summary["outcomes"]
    elif change == "empty_outcomes":
        summary["outcomes"] = []
    elif change == "nonlist_outcomes":
        summary["outcomes"] = {"ok": True}
    elif change == "nondict_outcome":
        summary["outcomes"].append(True)
    elif change == "nonbool_ok":
        summary["outcomes"][0]["ok"] = 1
    elif change == "failed_apply":
        summary["outcomes"][0]["ok"] = False
    elif change == "failed_continue":
        summary["outcomes"].append({"ok": False, "message": "continuation failed"})
    stdout = json.dumps(summary) + "\n"
    if change == "extra_row":
        stdout += json.dumps(summary) + "\n"
    elif change == "nonobject":
        stdout = json.dumps([summary]) + "\n"
    elif change == "diagnostic_before":
        stdout = "Unexpected diagnostic.\n" + stdout
    elif change == "diagnostic_after":
        stdout += "Unexpected diagnostic.\n"

    class Child:
        returncode = code

        def communicate(self, timeout):
            return stdout, stderr

        def poll(self):
            return self.returncode

    class Run:
        holder = "fake-holder"

        def left(self, cap):
            return cap

    monkeypatch.setattr(neighbour.subprocess, "Popen", lambda *a, **k: Child())
    out = tmp_path / "child"
    if change is None:
        leg = neighbour.trip(Run(), tmp_path, out, flags, 33, 52)
        assert leg["pending_temple"] is True
        assert leg["result"] == summary
    else:
        with pytest.raises(RouteError):
            neighbour.trip(Run(), tmp_path, out, flags, 33, 52)
    assert (out / "stdout.txt").read_text() == stdout
    assert (out / "stderr.txt").read_text() == stderr


def test_temple_guard_requires_story_and_return_bar_on_the_same_frame(tmp_path):
    declared = json.loads(neighbour.GUARDS.read_text())["guards"]
    temple = declared["temple_entry_continue"]
    assert temple["box"] == [88, 302, 700, 360]
    assert temple["sha256"] == "79b1f10c48f8f400095e26fbf9e4877144ad922863f8440af03decf66f048408"
    assert temple["and"] == [{"box": [186, 404, 586, 426],
                              "sha256": "604731cd6f2b106a3670ba258e49c2545af33d3742467843fcd3a8c0f9ad7fe9"}]
    assert temple["example"] == "WISH-367/amiga-neighbour/guard3/temple-entry-canonical.png"
    frame = Image.new("RGB", (720, 568), "black")
    frame.paste("blue", tuple(temple["box"]))
    frame.paste("white", tuple(temple["and"][0]["box"]))
    complete = tmp_path / "complete.png"
    frame.save(complete)
    rule = guard_rule(complete, temple["box"])
    rule["and"] = [guard_rule(complete, temple["and"][0]["box"])]
    rules = tmp_path / "synthetic-guards.json"
    rules.write_text(json.dumps({"temple": rule}))
    guards = PixelGuards(rules)
    assert guards("temple", complete)
    for label, box in (("changed_story", temple["box"]), ("changed_bar", temple["and"][0]["box"])):
        altered = frame.copy()
        altered.paste("red", tuple(box))
        path = tmp_path / f"{label}.png"
        altered.save(path)
        assert not guards("temple", path)


def test_private_temple_capture_matches_both_boxes_and_not_other_pages(tmp_path):
    cache = pathlib.Path.home() / ".cache/wish/acceptance"
    raw = cache / "WISH-367/amiga-neighbour/guard3/trip-2/002.png"
    well = cache / "WISH-367/amiga-neighbour/normal2/well-entry-canonical.png"
    other = [cache / f"WISH-367/amiga-live2/to52/{n:03d}.png" for n in (2, 3)]
    world = cache / "WISH-367/amiga-neighbour/normal2/screens/047-world.png"
    if not all(path.is_file() for path in (raw, well, world, *other)):
        pytest.skip("Private retained Temple, Well, world and other-Temple captures are unavailable")
    rules = json.loads(neighbour.GUARDS.read_text())["guards"]
    declared = rules["temple_entry_continue"]
    derivative = cache / declared["example"]
    if not derivative.is_file():
        pytest.skip("Private canonical Temple derivative is unavailable")
    canonical = tmp_path / "temple.png"
    canonical_file(raw, canonical)
    boxes = [declared["box"], declared["and"][0]["box"]]
    assert canonical.read_bytes() == derivative.read_bytes()
    assert box_digests(canonical, boxes) == {
        tuple(boxes[0]): declared["sha256"], tuple(boxes[1]): declared["and"][0]["sha256"]}
    guard_file = tmp_path / "guards.json"
    guard_file.write_text(json.dumps(rules))
    guards = PixelGuards(guard_file)
    assert guards("temple_entry_continue", derivative)
    for index, control in enumerate((well, world, *other)):
        canonical = tmp_path / f"control-{index}.png"
        canonical_file(control, canonical)
        assert not guards("temple_entry_continue", canonical)


def test_private_temple_clear_world_excludes_the_gate_page(tmp_path):
    screens = (pathlib.Path.home() / ".cache/wish/acceptance/WISH-367/amiga-neighbour/"
               "guard4/screens")
    frames = [screens / f"{number:03d}-world.png" for number in (51, 52, 53)]
    if not all(frame.is_file() for frame in frames):
        pytest.skip("Private retained Temple world captures 051/052/053 are unavailable")
    rules = json.loads(neighbour.GUARDS.read_text())["guards"]
    clear = rules["temple_clear_world"]
    assert clear["box"] == rules["world"]["box"]
    assert clear["sha256"] == rules["world"]["sha256"]
    assert clear["and"] == [{"box": [88, 302, 700, 360],
                             "sha256": "cef45536ff0f51ccc84d953ce7c3e08d407d4083029cc3efd7cce4a62825b730"}]
    guard_file = tmp_path / "guards.json"
    guard_file.write_text(json.dumps(rules))
    guards = PixelGuards(guard_file)
    for frame in frames:
        assert guards("world", frame)
    assert [guards("temple_clear_world", frame) for frame in frames] == [True, True, False]


def test_temple_clear_world_exports_as_a_two_box_guard(tmp_path):
    maps = neighbour.GUARDS.parent
    declared = json.loads(neighbour.GUARDS.read_text())["guards"]
    clear = declared["temple_clear_world"]
    spec = guardmaps._load(maps, "ssb")
    assert spec["guards"]["temple_clear_world"] == clear
    assert clear["also"] == ["world"]
    assert clear["box"] == declared["world"]["box"]
    assert clear["sha256"] == declared["world"]["sha256"]
    assert clear["and"] == [{"box": [88, 302, 700, 360],
                             "sha256": "cef45536ff0f51ccc84d953ce7c3e08d407d4083029cc3efd7cce4a62825b730"}]
    output = tmp_path / "export"
    assert guardmaps.main(["--maps", str(maps), "export", "--title", "ssb",
                           "--out", str(output)]) == 0
    exported = json.loads((output / "guards.json").read_text())
    assert exported["temple_clear_world"] == {
        key: clear[key] for key in ("box", "sha256", "and")}
    assert PixelGuards(output / "guards.json").rules == exported


def test_private_temple_east_edge_uses_the_registered_amiga_geo32():
    try:
        payload = every_port()["Silver Blades"]["Amiga"]["GEO32"]
    except (gamedisks.RegistryError, KeyError, OSError):
        pytest.skip("Private registered Silver Blades Amiga GEO32 is unavailable")
    geo = Geo(payload)
    assert geo.wall(2, 15, WEST) == 2
    assert geo.barrier(2, 15, WEST) == SOLID
    assert not geo.is_passable(2, 15, WEST)
    assert geo.wall(2, 15, EAST) == 1
    assert geo.barrier(2, 15, EAST) == 1
    assert geo.is_passable(2, 15, EAST)
    assert geo.script_id(3, 15) == 0


@pytest.mark.parametrize("failure", [None, "wrong_identity", "wrong_variable", "changed_story",
                                      "bar_only", "shut_gate", "changed_after", "wrong_after",
                                      "wrong_turn", "blocked_east", "changed_screen"])
def test_pending_temple_requires_one_guarded_return_and_fresh_world_before_step(
        tmp_path, monkeypatch, failure):
    names = [f"Member {n}" for n in range(6)]
    sources = {}
    for key in ("boot_source", "disk_b_source", "substitute", "published_df1", "df0", "df1"):
        disk = tmp_path / f"{key}.adf"
        disk.write_bytes(f"synthetic {key}".encode())
        sources[key] = {"path": str(disk), "sha256": hashlib.sha256(disk.read_bytes()).hexdigest()}
    manifest = {**sources, "disks": {key: sources[key] for key in ("df0", "df1")},
                "names_a": names, "state_a": {"area": 16, "x": 3, "y": 7, "facing": 2},
                "mode": "substitute_title", "title": "ssb", "loaded_letter": "D", "slot_letter": "D"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(neighbour, "preflight", lambda *args: (manifest, neighbour.time.time() + 3600))
    monkeypatch.setattr(neighbour.route_silver_blades, "title_for_substitute", lambda m: object())
    monkeypatch.setattr(neighbour.acceptance, "boot_lane", lambda *a, **k: {"holder": k["holder"]})
    monkeypatch.setattr(neighbour.acceptance, "halt_lane", lambda *a, **k: {"fetched": {"df0": {}, "df1": {}}})
    monkeypatch.setattr(neighbour.noencounters, "winuae_state_path", lambda holder: tmp_path / "gate.json")
    monkeypatch.setattr(neighbour.noencounters, "WinuaeState", lambda path: type("State", (), {
        "load": lambda self: {"on": False, "rows": []}})())
    events = []
    current = {"area": 16, "square": (3, 7, 2), "names": names, "variables": {}, "target": object()}

    class Guest:
        def _run(self, *a, **k):
            return '{"muted": true}'

        def silence(self, proof):
            return proof.is_file()

        def grab(self, state, raw, crop, timeout):
            raw.write_bytes(b"synthetic raw")
            crop.write_bytes(b"synthetic crop")
            events.append(("see", state))
            return True

        def press(self, holder, key, timeout):
            events.append(("press", key))
            if key == "RET" and current["area"] == 52 and failure == "wrong_after":
                current["square"] = (3, 15, 3)

        def snapshot(self, name, holder):
            events.append(("snapshot", name))

        def restore(self, name, holder):
            events.append(("restore", name))
            current.update(area=16, square=(3, 7, 2), variables={})

        def discard(self, name, holder):
            events.append(("discard", name))

    class Guards:
        rules = dict.fromkeys(("title", "party_menu", "load_picker", "loaded_menu", "journal",
                               "world", "well_entry_continue", "temple_entry_continue",
                               "temple_clear_world"))

        def __contains__(self, name):
            return name in self.rules

        def __call__(self, state, crop):
            if state == "temple_clear_world":
                events.append(("guard", state, current["area"], current["square"]))
            if state == "temple_entry_continue" and failure in ("changed_story", "bar_only"):
                return False
            if state == "world" and failure == "changed_after" and len([
                    e for e in events if e == ("press", "RET")]) == 2:
                return False
            if state == "temple_clear_world" and failure == "changed_screen" and (
                    "switch", "NP6") in events:
                return False
            return state != "journal"

    if failure in ("changed_story", "bar_only", "changed_after", "changed_screen"):
        original_see = neighbour.GuardedRun.see

        def quick_failed_screen(self, state, limit):
            if state == "temple_entry_continue" or (
                    state == "world" and failure == "changed_after"
                    and len([e for e in events if e == ("press", "RET")]) == 2) or (
                    state == "temple_clear_world" and failure == "changed_screen"
                    and ("switch", "NP6") in events):
                limit = 0.01
            return original_see(self, state, limit)

        monkeypatch.setattr(neighbour.GuardedRun, "see", quick_failed_screen)

    class Switch:
        def __init__(self, target):
            pass

        def on(self):
            events.append(("switch", "on"))
            return {"action": "on"}

        def keys(self, keys):
            events.append(("switch", *keys))
            assert len(keys) == 1 and keys[0] in ("NP6", "NP8")
            x, y, facing = current["square"]
            if keys == ["NP6"]:
                current["square"] = (x, y, facing if failure == "wrong_turn" else (facing + 1) % 4)
            elif current["area"] == 52:
                # GEO32 at (2,15): the west gate is solid; only east admits this step.
                if facing == EAST and failure != "blocked_east":
                    current["square"] = (3, 15, EAST)
            elif facing == WEST:
                current["square"] = (x - 1, y, facing)
            return {"pressed": keys}

        def off(self):
            events.append(("switch", "off"))
            return {"action": "off"}

    def execute(run, disks, out, flags, start, end):
        events.append(("trip", start, end))
        assert current["area"] == start
        current.update(area=end, square={33: (1, 1, 2), 52: (2, 15, 3),
                                         82: (1, 11, 1), 81: (15, 6, 3)}[end])
        if end == 52:
            current["variables"] = {"4C62": 5, "4C2A": 1, "4CFD": 255, "4CFE": 0}
            if failure == "wrong_identity":
                current["names"] = names[:-1] + ["Other"]
            if failure == "wrong_variable":
                current["variables"]["4C2A"] = 0
            pending = {"result": "idle", "settled": False, "areas_seen": [33, 52],
                       "arrival_keys": [], "arrival_answered": False,
                       "outcomes": [{"ok": True, "message": "applied"}],
                       "party_before": names, "party_after": names.copy()}

            class Child:
                returncode = 1

                def communicate(self, timeout):
                    return json.dumps(pending) + "\n", (
                        "Leg 1 (the trip) never became ready for Fast Travel.\n"
                        "The leg reached area 52 and the game is still waiting on its screen; "
                        "give its keys with --arrival-answer (repeat it for several screens).\n")

                def poll(self):
                    return self.returncode

            monkeypatch.setattr(neighbour.subprocess, "Popen", lambda *a, **k: Child())
            return neighbour.trip(run, disks, out, flags, start, end)
        out.mkdir()
        (out / "stdout.txt").write_text("synthetic child\n")
        (out / "stderr.txt").write_text("")
        if end == 81:
            current["variables"] = {"4CFD": 64, "4CFE": 85, "4C6C": 64, "4C6D": 85}
        return {"command": flags, "pending_well": end == 33, "pending_temple": end == 52,
                "result": {"result": "idle", "settled": end not in (33, 52),
                           "areas_seen": [start, end], "arrival_keys": [],
                           "party_before": names, "party_after": names},
                "stdout": str(out / "stdout.txt"), "stderr": str(out / "stderr.txt")}

    monkeypatch.setattr(neighbour.amigatrip, "gate", lambda *a: not (
        failure == "shut_gate" and len([e for e in events if e == ("press", "RET")]) == 2))
    args = argparse.Namespace(manifest=path, holder="fake-holder", out=tmp_path / "output",
                              budget=3600, wait_lane=0, retry_of=None)

    def read(holder):
        events.append(("read", current["area"], current["square"], tuple(current["names"])))
        return current.copy()

    options = dict(guest=Guest(), guards=Guards(), reader=read,
                   executor=execute, switch_factory=Switch)
    if failure:
        with pytest.raises(RouteError):
            neighbour.run(args, **options)
    else:
        receipt = neighbour.run(args, **options)
        assert receipt["success"] is True
        assert [(e[1], e[2]) for e in events if e[0] == "trip"] == [
            (16, 33), (33, 52), (16, 82), (82, 81)]
        assert [e[1] for e in events if e[0] == "switch"] == [
            "on", "NP6", "NP6", "NP8", "off", "on", "NP8", "off"]
        assert receipt["reads"]["temple_prompt"]["variables"]["4C2A"] == 1
        assert receipt["reads"]["52"]["square"] == (2, 15, 3)
        assert receipt["reads"]["52-turn-north"]["square"] == (2, 15, 0)
        assert receipt["reads"]["52-turn-east"]["square"] == (2, 15, 1)
        assert receipt["reads"]["52-step"]["square"] == (3, 15, 1)
        keys = [i for i, event in enumerate(events) if event in (("switch", "NP6"),
                                                                  ("switch", "NP8"))]
        assert len(keys) == 4
        before = ((2, 15, 3), (2, 15, 0), (2, 15, 1))
        after = ((2, 15, 0), (2, 15, 1), (3, 15, 1))
        for turn, index in enumerate(keys[:3]):
            previous = keys[turn - 1] if turn else events.index(("snapshot", "destination-52"))
            following = keys[turn + 1]
            assert ("guard", "temple_clear_world", 52, before[turn]) in events[previous:index]
            assert ("read", 52, before[turn], tuple(names)) in events[previous:index]
            assert ("guard", "temple_clear_world", 52, after[turn]) in events[index:following]
            assert ("read", 52, after[turn], tuple(names)) in events[index:following]
        assert ("snapshot", "destination-52") in events
    assert [e[1] for e in events if e[0] == "press" and e[1] == "RET"] == (
        ["RET"] if failure in ("wrong_identity", "wrong_variable", "changed_story", "bar_only")
        else ["RET", "RET"])
    if failure:
        if failure in ("wrong_turn", "blocked_east", "changed_screen"):
            assert ("snapshot", "destination-52") in events
            if failure == "blocked_east":
                assert ("switch", "NP8") in events
            else:
                assert ("switch", "NP8") not in events
            assert ("switch", "NP6") in events
        else:
            assert ("snapshot", "destination-52") not in events
            assert ("switch", "NP8") not in events
        assert not any(e[0] == "trip" and e[1] == 16 and e[2] == 82 for e in events)
    else:
        second_return = events.index(("press", "RET"), events.index(("trip", 33, 52)))
        assert events.index(("see", "temple_entry_continue")) < second_return
        assert second_return < events.index(("see", "world"), second_return) < events.index(
            ("snapshot", "destination-52"))
    saved = json.loads((args.out / "receipt.json").read_text())
    assert saved["success"] is (failure is None)
    assert {"discard": "s0"} in saved["cleanup"]
    assert saved["halt"]["fetched"] == {"df0": {}, "df1": {}}
    if failure in ("wrong_turn", "blocked_east", "changed_screen"):
        assert {"discard": "destination-52"} in saved["cleanup"]
        assert {"encounters": "off"} in saved["cleanup"]
        assert ("switch", "off") in events


def test_well_guard_requires_both_independent_boxes_on_one_screen(tmp_path):
    declared = json.loads(neighbour.GUARDS.read_text())["guards"]
    well = declared["well_entry_continue"]
    assert well["box"] == [88, 302, 700, 360]
    assert well["sha256"] == "c1297615077eee8f4a32bce0d85770fcf1b7893fad3b49194d8edba9b1c3954b"
    assert well["and"] == [{key: declared["continue"][key] for key in ("box", "sha256")}]
    assert well["example"] == "WISH-367/amiga-neighbour/normal2/well-entry-canonical.png"
    complete = tmp_path / "complete.png"
    frame = Image.new("RGB", (720, 568), "black")
    frame.paste("blue", tuple(well["box"]))
    frame.paste("white", tuple(well["and"][0]["box"]))
    frame.save(complete)
    rule = guard_rule(complete, well["box"])
    rule["and"] = [guard_rule(complete, well["and"][0]["box"])]
    file = tmp_path / "synthetic-guards.json"
    file.write_text(json.dumps({"well": rule}))
    guards = PixelGuards(file)
    assert guards("well", complete)
    for label, box in (("changed_story", well["box"]),
                       ("bar_only", well["box"]), ("changed_bar", well["and"][0]["box"])):
        altered = frame.copy()
        altered.paste("red" if label != "bar_only" else "black", tuple(box))
        shot = tmp_path / f"{label}.png"
        altered.save(shot)
        assert not guards("well", shot)


def test_an_overrunning_child_is_stopped_and_keeps_its_logs(tmp_path, monkeypatch):
    events = []

    class Child:
        returncode = -15

        def communicate(self, timeout):
            events.append(("communicate", timeout))
            if len(events) == 1:
                raise subprocess.TimeoutExpired("fasttravelrun", timeout)
            return "partial stdout\n", "partial stderr\n"

        def send_signal(self, signum):
            events.append(("terminate", signum))

        def poll(self):
            return self.returncode

    monkeypatch.setattr(neighbour.subprocess, "Popen", lambda *args, **kwargs: Child())

    class Run:
        holder = "fake-holder"

        def left(self, cap):
            return cap

    out = tmp_path / "child"
    with pytest.raises(RouteError, match="trip child exceeded its deadline") as failure:
        neighbour.trip(Run(), pathlib.Path("/synthetic/disks"), out, ["--to", "33"], 16, 33)
    assert isinstance(failure.value.__cause__, subprocess.TimeoutExpired)
    assert events == [("communicate", 480), ("terminate", neighbour.signal.SIGTERM),
                      ("communicate", 10)]
    assert (out / "stdout.txt").read_text() == "partial stdout\n"
    assert (out / "stderr.txt").read_text() == "partial stderr\n"
    assert neighbour.transport_timeout(failure.value) is False


def test_a_winvm_transport_overrun_is_retryable_only_with_its_timeout_cause():
    timeout = subprocess.TimeoutExpired("winvm", 20)
    try:
        raise RouteError("winvm ssh exceeded its 20.0s limit") from timeout
    except RouteError as error:
        assert neighbour.transport_timeout(error) is True
    assert neighbour.transport_timeout(RouteError("winvm ssh exceeded its 20.0s limit")) is False


class _ScriptedGuest:
    """Show one named screen per grab; record every key pressed."""

    def __init__(self, screens):
        self.screens = list(screens)
        self.keys = []

    def grab(self, state, raw, crop, timeout):
        shown = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        crop.write_text(shown)
        raw.write_text(shown)
        return True

    def press(self, holder, key, timeout):
        self.keys.append(key)


class _NamedGuards:
    rules = {name: {} for name in ("title", "party_menu", "load_picker", "loaded_menu",
                                   "journal", "world")}

    def __contains__(self, name):
        return name in self.rules

    def __call__(self, state, crop):
        return pathlib.Path(crop).read_text() == state


def _guarded_run(tmp_path, monkeypatch, screens):
    monkeypatch.setattr(neighbour.time, "sleep", lambda seconds: None)
    guest = _ScriptedGuest(screens)
    run = neighbour.GuardedRun(guest, "holder", tmp_path / "screens", _NamedGuards(),
                               neighbour.time.monotonic() + 60)
    return run, guest


def test_load_key_taken_before_the_picker_draws_waits_for_the_picker(tmp_path, monkeypatch):
    # The game highlights LOAD SAVED GAME and reads the disk before the picker appears;
    # the party menu guard still matches those frames.
    run, guest = _guarded_run(tmp_path, monkeypatch, [
        "party_menu", "party_menu", "party_menu", "load_picker"])
    run.press("party_menu", "L")
    run.press("load_picker", "D")
    assert guest.keys == ["L", "D"]
    assert [e.get("screen") for e in run.events if "screen" in e] == [
        "party_menu", "load_picker"]


def test_load_key_the_game_never_took_stops_without_pressing_again(tmp_path, monkeypatch):
    run, guest = _guarded_run(tmp_path, monkeypatch, ["party_menu"])
    run.press("party_menu", "L")
    with pytest.raises(RouteError, match=r"load_picker did not match within 0.05s \(still party_menu\)"):
        run.see("load_picker", 0.05)
    assert guest.keys == ["L"]


def test_a_different_known_screen_after_a_key_still_stops_at_once(tmp_path, monkeypatch):
    run, guest = _guarded_run(tmp_path, monkeypatch, ["party_menu", "title"])
    run.press("party_menu", "L")
    with pytest.raises(RouteError, match="expected load_picker, saw title"):
        run.see("load_picker", 60)
    assert guest.keys == ["L"]


def test_journal_match_ends_the_wait_past_the_loaded_menu(tmp_path, monkeypatch):
    # B goes out on the loaded menu; once the journal is recognised, a return to the
    # loaded menu while waiting for the world stops at once instead of being polled past.
    source = tmp_path / "inputs"
    source.mkdir()
    inputs = {}
    for key in ("boot_source", "disk_b_source", "substitute", "published_df1", "df0", "df1"):
        path = source / f"{key}.adf"
        path.write_bytes((key + " synthetic disk").encode())
        inputs[key] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {**inputs, "disks": {key: inputs[key] for key in ("df0", "df1")},
                "registered": {key: inputs[key] for key in ("boot_source", "disk_b_source",
                                                              "substitute")}
                | {"published": inputs["published_df1"]},
                "state_a": {"area": 16, "x": 3, "y": 7, "facing": 2},
                "names_a": [f"Member {n}" for n in range(6)],
                "mode": "substitute_title", "title": "ssb", "loaded_letter": "D",
                "slot_letter": "D"}
    original = tmp_path / "original.json"
    original.write_text(json.dumps(manifest))

    class Guest(_ScriptedGuest):
        def grab(self, state, raw, crop, timeout):
            # Two grabs bound the wait for the world: one is enough to stop on the loaded menu.
            if state == "world" and len(list(crop.parent.glob("*-world.png"))) >= 2:
                raise AssertionError("the wait for the world polled past the loaded menu")
            return super().grab(state, raw, crop, timeout)

        def _run(self, *args, **kwargs):
            return '{"muted": true}'

        def silence(self, proof):
            return True

        def answer_io(self, holder):
            return None, None

    class Guards(_NamedGuards):
        rules = dict.fromkeys(("title", "party_menu", "load_picker", "loaded_menu", "journal",
                                "world", "well_entry_continue", "temple_entry_continue",
                                "temple_clear_world"))

    class State:
        def load(self):
            return {"on": False, "rows": []}

    guest = Guest(["title", "party_menu", "load_picker", "loaded_menu", "journal",
                   "loaded_menu"])
    monkeypatch.setattr(neighbour.route_silver_blades, "title_for_substitute", lambda m: object())
    monkeypatch.setattr(gamedisks, "names", lambda: ["codewheel"])
    monkeypatch.setattr(neighbour.route_silver_blades, "journal_preflight", lambda interpreter: None)
    monkeypatch.setattr(neighbour.amigabladesjournal, "tables", lambda adf: [object()])
    monkeypatch.setattr(neighbour.amigabladesjournal, "answer", lambda *a, **k: True)
    monkeypatch.setattr(neighbour, "bounded_answer", lambda seconds: contextlib.nullcontext())
    monkeypatch.setattr(neighbour.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(neighbour.acceptance, "boot_lane", lambda *a, **k: {})
    monkeypatch.setattr(neighbour.acceptance, "halt_lane", lambda *a, **k: {})
    monkeypatch.setattr(neighbour.noencounters, "WinuaeState", lambda path: State())
    monkeypatch.setattr(neighbour.noencounters, "winuae_state_path", lambda holder: tmp_path / "gate.json")
    args = argparse.Namespace(manifest=original, holder="fake-holder", out=tmp_path / "result",
                              budget=60, wait_lane=0, retry_of=None)
    with pytest.raises(RouteError, match="expected world, saw loaded_menu"):
        neighbour.run(args, guest=guest, guards=Guards(),
                      reader=lambda holder: pytest.fail("the world was never shown"))
    assert guest.keys == ["P", "L", "D", "B"]


def test_timeout_names_the_pressed_screen_only_when_it_was_last_shown(tmp_path, monkeypatch):
    run, guest = _guarded_run(tmp_path, monkeypatch, ["party_menu", "party_menu", "unknown"])
    run.press("party_menu", "L")
    with pytest.raises(RouteError, match=r"load_picker did not match within 0.05s; last shot"):
        run.see("load_picker", 0.05)
    assert guest.keys == ["L"]


def test_a_match_ends_the_wait_past_the_pressed_screen(tmp_path, monkeypatch):
    run, guest = _guarded_run(tmp_path, monkeypatch, ["party_menu", "load_picker", "party_menu"])
    run.press("party_menu", "L")
    run.see("load_picker", 60)
    with pytest.raises(RouteError, match="expected loaded_menu, saw party_menu"):
        run.see("loaded_menu", 60)
    assert guest.keys == ["L"]


@pytest.mark.parametrize("change", [None, "no_bar", "unguarded", "unlogged", "two_answers",
                                    "two_keys", "other_key", "not_answered", "unanswered_flag",
                                    "other_leg", "no_flag", "unreadable_log"])
def test_village_arrival_takes_one_return_only_on_the_continue_bar(tmp_path, monkeypatch, change):
    # guard6's way back into the Frost giant village stopped on "You have reached the
    # other end of the village" over PRESS RETURN; a player presses Return once there.
    names = [f"Member {n}" for n in range(6)]
    keys = {"two_keys": ["RET", "RET"], "other_key": ["N"], "not_answered": []}.get(change, ["RET"])
    summary = {"result": "idle", "settled": True, "areas_seen": [82, 81],
               "arrival_keys": keys, "arrival_answered": bool(keys) and change != "unanswered_flag",
               "party_before": names, "party_after": names.copy()}
    flags, start, end = list(neighbour.VILLAGE_FLAGS), 82, 81
    if change == "other_leg":
        flags, start, end, summary["areas_seen"] = ["--to", "82"], 16, 82, [16, 82]
    elif change == "no_flag":
        flags = [flag for flag in flags if flag not in ("--arrival-answer", "RET")]
    answers = [{"event": "arrival_answer", "key": key, "at_continue": change != "unguarded"}
               for key in keys]
    if change == "two_answers":
        answers *= 2
    elif change == "unlogged":
        answers = []
    lines = [{"event": "legality", "ok": True}, *answers, {"event": "settle", "gate": True}]

    class Child:
        returncode = 0

        def communicate(self, timeout):
            return json.dumps(summary) + "\n", ""

        def poll(self):
            return self.returncode

    def popen(command, **kwargs):
        out = pathlib.Path(command[command.index("--out") + 1])
        log = out / "fasttravel.jsonl"
        if change == "unreadable_log":
            log.write_text("not json\n")
        elif change != "no_bar":
            log.write_text("".join(json.dumps(line) + "\n" for line in lines))
        else:
            log.write_text(json.dumps({"event": "arrival_answer_held",
                                       "reason": "the PRESS RETURN bar is absent"}) + "\n")
        return Child()

    class Run:
        holder = "fake-holder"

        def left(self, cap):
            return cap

    monkeypatch.setattr(neighbour.subprocess, "Popen", popen)
    out = tmp_path / "child"
    if change in (None, "not_answered"):
        leg = neighbour.trip(Run(), tmp_path, out, flags, start, end)
        assert leg["result"]["arrival_keys"] == keys
        assert leg["command"][-len(flags):] == flags
    else:
        reason = ("continue bar" if change in ("no_bar", "unguarded", "unlogged", "two_answers",
                                               "unreadable_log") else "trip diverged")
        with pytest.raises(RouteError, match=reason):
            neighbour.trip(Run(), tmp_path, out, flags, start, end)
