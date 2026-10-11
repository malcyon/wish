"""The guarded neighbour wrapper must stop and clean up on an unknown load screen."""

import argparse
import hashlib
import json
import pathlib
import subprocess

import pytest

from tools.amiga import ssbneighbour as neighbour
from tools.amiga.winuaesession import RouteError, ShotTimedOut


@pytest.mark.parametrize("unknown_picker,failure", [
    (False, None), (True, None), (False, "snapshot_lost"),
    (False, "snapshot_before_create"), (False, "shot_timeout"),
    (False, "child_timeout"),
])
def test_one_lane_proves_both_neighbour_legs_and_cleans_up(tmp_path, monkeypatch,
                                                             unknown_picker, failure):
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
            crop.write_bytes(b"synthetic cropped")
            return True

        def press(self, holder, key, timeout):
            events.append(("press", key))

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
                              "journal", "world"))

        def __contains__(self, name):
            return name in self.rules

        def __call__(self, state, crop):
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
            assert keys == ["NP8"]
            x, y, facing = current["square"]
            current["square"] = (x - 1, y, facing) if current["area"] == 81 else (x + 1, y, facing)
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
        out.mkdir()
        (out / "stdout.txt").write_text(f"{start} -> {end}\n")
        (out / "stderr.txt").write_text("")
        positions = {33: (3, 3, 1), 52: (2, 15, 3), 82: (1, 11, 1), 81: (15, 6, 3)}
        current.update(area=end, square=positions[end])
        if end == 52:
            current["variables"] = {"4C62": 5, "4C2A": 0}
        if end == 81:
            current["variables"] = dict.fromkeys(("4CFD", "4C6C"), 64) | dict.fromkeys(("4CFE", "4C6D"), 85)
        return {"command": flags, "result": {"areas_seen": [start, end], "result": "idle",
                                           "settled": True, "arrival_keys": [],
                                           "party_before": names, "party_after": names},
                "stdout": str(out / "stdout.txt"), "stderr": str(out / "stderr.txt")}

    monkeypatch.setattr(neighbour.route_silver_blades, "title_for_substitute", lambda m: object())
    monkeypatch.setattr(neighbour.acceptance, "boot_lane", boot)
    monkeypatch.setattr(neighbour.acceptance, "halt_lane", halt)
    monkeypatch.setattr(neighbour.noencounters, "WinuaeState", lambda path: State())
    monkeypatch.setattr(neighbour.noencounters, "winuae_state_path", lambda holder: tmp_path / "gate.json")
    args = argparse.Namespace(manifest=original, holder="fake-holder", out=tmp_path / "result",
                              budget=3600, wait_lane=0, retry_of=None)
    options = dict(guest=Guest(), guards=Guards(), reader=lambda holder: current.copy(),
                   executor=execute, switch_factory=Switch)
    if unknown_picker or failure:
        reason = "load_picker" if unknown_picker else {
            "snapshot_lost": "snapshot response lost",
            "snapshot_before_create": "snapshot creation stopped",
            "shot_timeout": "exceeded its",
            "child_timeout": "trip child exceeded its deadline",
        }[failure]
        with pytest.raises(RouteError, match=reason):
            neighbour.run(args, **options)
    else:
        receipt = neighbour.run(args, **options)
        assert receipt["success"] is True
        assert [(v[1], v[2]) for v in events if v[0] == "trip"] == [
            (16, 33), (33, 52), (16, 82), (82, 81)]
        assert [v[3] for v in events if v[0] == "trip"] == [
            ("--to", "33"),
            ("--waypoint", "52,7,3,2", "--back", "--peek-var", "4C62,4C2A,4CFD,4CFE"),
            ("--to", "82"),
            ("--waypoint", "81,5,8,1", "--back", "--peek-var", "4CFD,4CFE,4C6C,4C6D")]
        assert len({v[4] for v in events if v[0] == "trip"}) == 4
        assert len({v["stdout"] for v in receipt["trips"]}) == 4
        assert all((args.out / f"trip-{n}" / "stdout.txt").is_file() for n in range(1, 5))
        assert ("restore", "s0") in events
        assert receipt["reads"]["52"]["variables"]["4C62"] == 5
        assert receipt["reads"]["81"]["square"] == (15, 6, 3)
        assert receipt["reads"]["81-step"]["square"] == (14, 6, 3)
        assert [v[1] for v in events if v[0] == "switch"] == ["on", "NP8", "off"] * 2
    assert [v[1] for v in events if v[0] == "press"] == (
        [] if failure == "shot_timeout" else
        ["P", "L"] if unknown_picker else ["P", "L", "D", "B"])
    if unknown_picker:
        assert not any(v[0] == "trip" for v in events)
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
    assert saved["success"] is (not unknown_picker and failure is None)
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
