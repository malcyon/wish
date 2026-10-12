"""The Silver Blades Return proof accepts only guarded entrance landings, then saves and reloads."""

import argparse
import hashlib
import json
import pathlib

import pytest

from automap import gamedisks
from tools.amiga import ssbreturn as driver
from tools.amiga.winuaesession import RouteError

NAMES = [f"Member {n}" for n in range(6)]


def test_the_four_returns_carry_the_rederived_arguments():
    assert [(leg.dest, leg.flags()) for leg in driver.RETURNS] == [
        (82, ["--waypoint", "82,5,5,1", "--back", "--peek-var", "4CFD,4CFE,4C6C,4C6D"]),
        (51, ["--waypoint", "51,8,8,1", "--back", "--arrival-answer", "Return",
              "--peek-var", "4CFD,4CFE,4C6A,4C6F"]),
        (81, ["--waypoint", "81,5,8,1", "--back", "--arrival-answer", "l",
              "--arrival-answer", "Return", "--arrival-answer", "Return",
              "--peek-var", "4CFD,4CFE,4C6C,4C6D"]),
        (52, ["--waypoint", "52,7,3,2", "--back", "--arrival-answer", "Return",
              "--arrival-answer", "Return", "--peek-var", "4CFD,4CFE"]),
    ]
    # The ruling's normal entrances, in the first poll of each destination.
    assert {leg.dest: leg.landing for leg in driver.RETURNS} == {
        82: (1, 11, 1), 51: (3, 3, 1), 81: (0, 8, 1), 52: (7, 0, 2)}
    assert driver.RETURNS[-1].dest == 52


def _child_log(leg, *, landing=None, bar=True, keys=None, extra_read=None):
    keys = list(leg.keys) if keys is None else keys
    lines = [{"event": "legality", "ok": True},
             {"event": "read", "why": "before", "area": 16, "square": [3, 7, 2]}]
    if extra_read:
        lines.append(extra_read)
    lines.append({"event": "read", "why": "poll", "area": leg.dest,
                  "square": list(landing or leg.landing)})
    lines += [{"event": "arrival_answer", "key": key, "at_continue": bar} for key in keys]
    lines.append({"event": "read", "why": "after", "area": leg.end[0],
                  "square": list(leg.end[1])})
    return "".join(json.dumps(line) + "\n" for line in lines)


@pytest.mark.parametrize("dest", [82, 51, 81, 52])
@pytest.mark.parametrize("change", [None, "code", "unsettled", "areas", "keys", "answered",
                                    "party", "unlogged", "unguarded", "landing", "two_rows",
                                    "early_wrong_read"])
def test_a_return_child_is_accepted_only_on_its_entrance_and_guarded_keys(
        tmp_path, monkeypatch, dest, change):
    leg = next(leg for leg in driver.RETURNS if leg.dest == dest)
    summary = {"result": "idle", "settled": change != "unsettled",
               "areas_seen": list(leg.areas) + ([33] if change == "areas" else []),
               "arrival_keys": list(leg.keys) + (["N"] if change == "keys" else []),
               "arrival_answered": bool(leg.keys) != (change == "answered"),
               "party_before": NAMES, "party_after": NAMES[:5] + (["Other"] if change == "party"
                                                                 else NAMES[5:])}
    log = _child_log(leg, landing=(9, 9, 0) if change == "landing" else None,
                     bar=change != "unguarded",
                     keys=[] if change == "unlogged" else None,
                     extra_read=({"event": "read", "why": "poll", "area": leg.dest,
                                  "square": [9, 9, 0]}
                                 if change == "early_wrong_read" else None))
    stdout = json.dumps(summary) + "\n" + (json.dumps(summary) + "\n" if change == "two_rows" else "")

    class Child:
        returncode = 1 if change == "code" else 0

        def communicate(self, timeout):
            return stdout, ""

        def poll(self):
            return self.returncode

    def popen(command, **kwargs):
        out = pathlib.Path(command[command.index("--out") + 1])
        (out / "fasttravel.jsonl").write_text(log)
        return Child()

    class Run:
        holder = "fake-holder"

        def left(self, cap):
            return cap

    monkeypatch.setattr(driver.nb.subprocess, "Popen", popen)
    out = tmp_path / "child"
    unguarded_ok = change == "unguarded" and "Return" not in leg.keys
    unlogged_ok = change == "unlogged" and not leg.keys
    if change is None or unguarded_ok or unlogged_ok:
        child = driver.return_leg(Run(), tmp_path, out, leg)
        assert child["landing"]["square"] == list(leg.landing)
        assert child["command"][-len(leg.flags()):] == leg.flags()
    else:
        with pytest.raises(RouteError, match=f"into {dest}"):
            driver.return_leg(Run(), tmp_path, out, leg)


def _manifest(tmp_path):
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
                "state_a": {"area": 16, "x": 3, "y": 7, "facing": 2}, "names_a": NAMES,
                "mode": "substitute_title", "title": "ssb", "loaded_letter": "D",
                "slot_letter": "D"}
    path = tmp_path / "original.json"
    path.write_text(json.dumps(manifest))
    return path, manifest


def _fake_run(tmp_path, monkeypatch, *, slot_place=None, landing_fails=None):
    original, manifest = _manifest(tmp_path)
    events = []
    current = {"area": 16, "square": (3, 7, 2)}

    class Guest:
        def _run(self, *args, **kwargs):
            return '{"muted": true}'

        def silence(self, proof):
            return proof.exists()

        def grab(self, state, raw, crop, timeout):
            raw.write_text(state)
            crop.write_text(state)
            return True

        def press(self, holder, key, timeout):
            events.append(("press", holder, key))

        def snapshot(self, name, holder):
            events.append(("snapshot", holder, name))

        def restore(self, name, holder):
            events.append(("restore", holder, name))
            current.update(area=16, square=(3, 7, 2))

        def discard(self, name, holder):
            events.append(("discard", holder, name))

    class Guards:
        rules = dict.fromkeys(driver.GUARDS_NEEDED)

        def __contains__(self, name):
            return name in self.rules

        def __call__(self, state, crop):
            return state != "journal" and pathlib.Path(crop).read_text() == state

    class State:
        def load(self):
            return {"on": False, "rows": []}

    class Switch:
        def __init__(self, target):
            pass

        def on(self):
            events.append(("switch", "on"))
            return {"action": "on", "rows": []}

        def keys(self, keys):
            events.append(("switch", *keys))
            leg = next((leg for leg in driver.RETURNS if leg.end[0] == current["area"]
                        and leg.end[1] == current["square"]), None)
            current["square"] = leg.step if leg else driver.STEP_AFTER_SAVE
            return {"pressed": keys}

        def off(self):
            events.append(("switch", "off"))
            return {"action": "off"}

    def boot(local, prepared, title, **kwargs):
        events.append(("boot", kwargs["holder"]))
        if kwargs["holder"] == "ret2":
            current.update(area=52, square=(7, 1, 2))
        return {"holder": kwargs["holder"]}

    def halt(guest, holder, **kwargs):
        events.append(("halt", holder))
        fetched = tmp_path / f"fetched-{holder}.adf"
        fetched.write_bytes(b"game-written disk")
        return {"fetched": {"df0": {"path": str(fetched)}}}

    def execute(run, disks, out, leg):
        events.append(("return", leg.dest))
        out.mkdir()
        (out / "001.png").write_bytes(b"arrival frame")
        if leg.dest == landing_fails:
            raise RouteError(f"Return into {leg.dest} first read, not the entrance")
        current.update(area=leg.end[0], square=leg.end[1])
        return {"landing": {"square": list(leg.landing)}}

    def prepare(df0, run_id, **kwargs):
        events.append(("prepare", pathlib.Path(df0).name, run_id, kwargs["letter"]))
        path = tmp_path / "reload-prepare.json"
        path.write_text(json.dumps({**manifest, "state_a": driver.SAVED}))
        return path

    def slot(df0, letter):
        return {"sha256": "ab", "place": slot_place or driver.SAVED, "names": NAMES}

    def reader(holder):
        return {"area": current["area"], "square": current["square"], "names": NAMES,
                "variables": {}, "target": object()}

    monkeypatch.setattr(driver.route_silver_blades, "title_for_substitute", lambda m: object())
    monkeypatch.setattr(gamedisks, "names", lambda: ["codewheel"])
    monkeypatch.setattr(driver.route_silver_blades, "journal_preflight", lambda interpreter: None)
    monkeypatch.setattr(driver.amigabladesjournal, "tables", lambda adf: [object()])
    monkeypatch.setattr(driver.acceptance, "boot_lane", boot)
    monkeypatch.setattr(driver.acceptance, "halt_lane", halt)
    monkeypatch.setattr(driver.noencounters, "WinuaeState", lambda path: State())
    monkeypatch.setattr(driver.noencounters, "winuae_state_path", lambda holder: tmp_path / "g.json")
    monkeypatch.setattr(driver.nb.time, "sleep", lambda seconds: None)
    args = argparse.Namespace(manifest=original, holder="ret1", reload_holder="ret2",
                              out=tmp_path / "result", budget=3600, wait_lane=0)
    options = dict(guest=Guest(), guards=Guards(), reader=reader, executor=execute,
                   switch_factory=Switch, preparer=prepare, slot_reader=slot)
    return args, options, events


def test_four_returns_save_and_reload_in_order(tmp_path, monkeypatch):
    args, options, events = _fake_run(tmp_path, monkeypatch)
    receipt = driver.run(args, **options)
    assert receipt["success"] is True
    load = [("press", "ret1", key) for key in "PLDB"]
    assert events[:6] == [("boot", "ret1"), *load, ("snapshot", "ret1", "s0")]
    legs = [e for e in events if e[0] in ("return", "restore")]
    assert legs == [("return", 82), ("restore", "ret1", "s0"), ("return", 51),
                    ("restore", "ret1", "s0"), ("return", 81), ("restore", "ret1", "s0"),
                    ("return", 52)]
    # Each Return is followed by one switched step, the switch off again.
    after = [events[i + 1:i + 4] for i, e in enumerate(events) if e[0] == "return"]
    assert after == [[("switch", "on"), ("switch", "NP8"), ("switch", "off")]] * 4
    save = events.index(("press", "ret1", "E"))
    assert events[save:save + 6] == [("press", "ret1", "E"), ("press", "ret1", "S"),
                                     ("press", "ret1", "B"), ("press", "ret1", "N"),
                                     ("discard", "ret1", "s0"), ("halt", "ret1")]
    assert events[save + 6:save + 12] == [("prepare", "fetched-ret1.adf", "result-reload", "B"),
                                          ("boot", "ret2"),
                                          *[("press", "ret2", key) for key in "PLDB"]]
    assert events[-4:] == [("switch", "on"), ("switch", "NP8"), ("switch", "off"),
                           ("halt", "ret2")]
    assert {dest: receipt["returns"][dest]["after"]["square"] for dest in receipt["returns"]} == {
        "82": (1, 11, 1), "51": (3, 3, 1), "81": (3, 5, 3), "52": (7, 0, 2)}
    assert {dest: receipt["returns"][dest]["step"]["square"] for dest in receipt["returns"]} == {
        "82": (2, 11, 1), "51": (4, 3, 1), "81": (2, 5, 3), "52": (7, 1, 2)}
    assert receipt["save"]["place"] == driver.SAVED
    assert receipt["reloaded"]["square"] == (7, 1, 2)
    assert receipt["reloaded_step"]["square"] == driver.STEP_AFTER_SAVE
    assert receipt["shots"]["return-82/001.png"] == hashlib.sha256(b"arrival frame").hexdigest()
    written = json.loads((args.out / "receipt.json").read_text())
    assert written["success"] is True


def test_a_save_in_the_wrong_place_stops_before_the_reload_boot(tmp_path, monkeypatch):
    args, options, events = _fake_run(tmp_path, monkeypatch,
                                      slot_place={"area": 52, "x": 7, "y": 0, "facing": 2})
    with pytest.raises(RouteError, match="slot B is not the Temple party"):
        driver.run(args, **options)
    assert ("boot", "ret2") not in events
    assert events.count(("halt", "ret1")) == 1
    assert ("discard", "ret1", "s0") in events


def test_a_return_off_the_entrance_stops_the_run_and_halts_once(tmp_path, monkeypatch):
    args, options, events = _fake_run(tmp_path, monkeypatch, landing_fails=51)
    with pytest.raises(RouteError, match="Return into 51"):
        driver.run(args, **options)
    assert ("return", 81) not in events and ("press", "ret1", "E") not in events
    assert events.count(("halt", "ret1")) == 1
    receipt = json.loads((args.out / "receipt.json").read_text())
    assert receipt["success"] is False and list(receipt["returns"]) == ["82"]


def test_the_reload_needs_its_own_holder(tmp_path, monkeypatch):
    args, options, events = _fake_run(tmp_path, monkeypatch)
    args.reload_holder = args.holder
    with pytest.raises(RouteError, match="its own holder"):
        driver.run(args, **options)
    assert events == []
