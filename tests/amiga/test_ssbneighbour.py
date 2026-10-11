"""The guarded neighbour wrapper must stop and clean up on an unknown load screen."""

import argparse
import hashlib
import json

import pytest

from tools.amiga import ssbneighbour as neighbour
from tools.amiga.winuaesession import RouteError


@pytest.mark.parametrize("unknown_picker", [False, True])
def test_one_lane_proves_both_neighbour_legs_and_cleans_up(tmp_path, monkeypatch,
                                                             unknown_picker):
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
            raw.write_bytes(b"synthetic raw")
            crop.write_bytes(b"synthetic cropped")
            return True

        def press(self, holder, key, timeout):
            events.append(("press", key))

        def snapshot(self, name, holder):
            events.append(("snapshot", name))

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
    if unknown_picker:
        with pytest.raises(RouteError, match="load_picker"):
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
    assert [v[1] for v in events if v[0] == "press"] == (["P", "L"] if unknown_picker else ["P", "L", "D", "B"])
    if unknown_picker:
        assert not any(v[0] == "trip" for v in events)
    assert [v[0] for v in events if v[0] in {"stop", "fetch", "release"}] == [
        "stop", "fetch", "release"]
    assert all(hashlib.sha256((source / f"{key}.adf").read_bytes()).hexdigest() == inputs[key]["sha256"]
               for key in inputs)
    saved = json.loads((args.out / "receipt.json").read_text())
    assert saved["success"] is not unknown_picker
    if unknown_picker:
        assert list((args.out / "screens").glob("*-load_picker-raw.png"))
