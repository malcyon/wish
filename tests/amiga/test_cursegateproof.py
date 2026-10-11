"""A no-save, one-snapshot Curse comparison on synthetic engine and screen states."""

from __future__ import annotations

import hashlib
import json
import os
import time
from argparse import Namespace
from pathlib import Path

import pytest

from tools.amiga import cursegateproof as proof
from tools.amiga import screens as screen_rules
from tools.amiga.winuaesession import RouteError

ENTRY_BYTES = bytes(range(20))  # Generated, not a game script or specimen.
ORIGINAL = bytes((8, 0, 100, 1, 121, 127))


class SyntheticAlarm:
    """Test-only Windows stand-in for the driver's POSIX alarm API."""

    SIGALRM = 14
    ITIMER_REAL = 0

    def __init__(self):
        self.handler = None
        self.timers = []

    def getsignal(self, signum):
        assert signum == self.SIGALRM
        return self.handler

    def signal(self, signum, handler):
        assert signum == self.SIGALRM
        previous, self.handler = self.handler, handler
        return previous

    def setitimer(self, which, seconds):
        assert which == self.ITIMER_REAL and seconds >= 0
        self.timers.append(seconds)


def _windows_alarm(monkeypatch):
    if os.name == "nt":
        alarm = SyntheticAlarm()
        monkeypatch.setattr(proof, "signal", alarm)
        return alarm
    return None


class Pipe:
    """Two synthetic hunk pointers and a generated six-byte opcode cell."""

    data_base = 0x10000
    pointer = 0x20000

    def __init__(self):
        self.cells = {self.data_base + 0x5006: self.pointer.to_bytes(4, "big"),
                      self.pointer + 0x8000: ENTRY_BYTES,
                      self.pointer + 0x9952: ORIGINAL}
        self.writes = []

    def locate(self):
        return self.data_base

    def read(self, address, size):
        assert address in self.cells and len(self.cells[address]) == size
        return self.cells[address]

    def write(self, address, value):
        assert address == self.pointer + 0x9952
        assert len(value) == 1
        self.writes.append((address, bytes(value)))
        self.cells[address] = bytes(value) + self.cells[address][1:]


class Journal:
    """The switch's persisted state, independent of screen transitions."""

    def __init__(self):
        self.path = Path("synthetic-journal.json")
        self.on = False
        self.rows = []

    def load(self):
        return {"on": self.on, "rows": list(self.rows)}


class Guest:
    """No emulator: record the ordering of snapshot, restore and discard."""

    def __init__(self, env):
        self.env = env
        self.calls = []
        self.saved = None

    def snapshot(self, name, holder):
        assert self.saved is None
        self.calls.append("snapshot")
        self.saved = (self.env.square, self.env.mode, self.env.pipe.read(
            self.env.pipe.pointer + 0x9952, 6))
        return {"name": name}

    def restore(self, name, holder):
        assert not self.env.journal.on and not self.env.journal.rows
        assert self.env.pipe.read(self.env.pipe.pointer + 0x9952, 6) == ORIGINAL
        self.calls.append("restore")
        self.env.square, self.env.mode, self.env.pipe.cells[
            self.env.pipe.pointer + 0x9952] = self.saved
        return {"name": name}

    def discard(self, name, holder):
        self.calls.append("discard")


class Switch:
    """Change only the generated ECL01 opcode and persist its one-byte journal."""

    def __init__(self, env):
        self.env = env
        self.calls = []
        self.stopped = False
        self.fail_off = False
        self.press = None

    def on(self):
        self.calls.append("on")
        if not self.stopped:
            self.env.pipe.write(self.env.pipe.pointer + 0x9952, b"\x09")
            self.env.journal.on = True
            self.env.journal.rows = [{"spec": proof.GATE, "original": "08", "changed": "09"}]
        return {"action": "on", "rows": [
            {"row": "*0x5006+0x8739", "stopped": "the other area is absent"},
            {"row": proof.GATE, **({"stopped": "hash mismatch"} if self.stopped else {
                "address": self.env.pipe.pointer + 0x9952, "new": "09"})}]}

    def keys(self, keys):
        self.calls.append(("keys", tuple(keys)))
        (self.press or self.env.shots.press)(keys[0])
        return {"action": "keys", "pressed": list(keys), "applied": []}

    def off(self):
        self.calls.append("off")
        if self.fail_off and self.env.journal.on:
            return {"action": "off", "error": "synthetic restore failed"}
        if self.env.journal.on or self.env.journal.rows:
            self.env.pipe.write(self.env.pipe.pointer + 0x9952, b"\x08")
        self.env.journal.on = False
        self.env.journal.rows = []
        return {"action": "off", "rows": [{"repaired": True}]}


class Screens:
    """The measured route's screen transitions, without game image fixtures."""

    def __init__(self, env, folder: Path):
        self.env, self.folder = env, folder
        self.folder.mkdir()
        self.events = []
        self.keys = []

    def see(self, name, seconds, **options):
        assert name in {"title", "load_picker", "loaded_menu", "sheet"}
        self.events.append({"crop": str(self.folder / "synthetic-world.png")})

    def world_at(self, target, expected, seconds, **options):
        self.events.append({"crop": str(self.folder / "synthetic-world.png")})
        reading = self.env.reading()
        proof.at_world(reading, expected)
        return reading

    def press(self, key):
        assert key in {"L", "B", "V", "E", "NP2", "NP8"}
        self.keys.append(key)
        if key == "B" and self.env.square is None:
            self.env.square = (4, 14, 1)
        elif key == "NP2":
            self.env.square = (4, 14, 3)
        elif key == "NP8":
            x, y, face = self.env.square
            assert x > 2
            self.env.square = (x - 1, y, face)
            self.env.mode = (5 if not self.env.journal.on and x - 1 ==
                             self.env.fight_at else 4)

    def receipt(self):
        pass


class Scenario:
    def __init__(self, folder, fight_at=3):
        self.pipe, self.journal = Pipe(), Journal()
        self.square, self.mode, self.fight_at = None, 4, fight_at
        self.guest = Guest(self)
        self.switch = Switch(self)
        self.shots = Screens(self, folder / "shots")

    def reading(self):
        x, y, face = self.square
        return {"area": 1, "square": self.square, "mode": self.mode,
                "attribute": 0, "fix": {"x": x, "y": y, "facing": face,
                                         "world_map": False},
                "names": list(proof.NAMES),
                "variables": {f"{v:04X}": {"value": 0, "note": None}
                              for v in proof.VARS}}


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    env = Scenario(tmp_path)
    monkeypatch.setattr(proof, "ENTRY", hashlib.sha256(ENTRY_BYTES).hexdigest()[:8])
    monkeypatch.setattr(proof, "live", lambda target, names=False: env.reading())
    monkeypatch.setattr(proof.screens, "checked_rule", lambda *a, **k: {"sha256": "synthetic"})

    def observe(shots, target, index, before, guard, *, replay):
        after = env.reading()
        outcome = proof.classify(
            world=env.mode == 4, combat=env.mode == 5 and env.fight_at != 0,
            mode=env.mode, prior=before, index=index)
        return outcome, {"outcome": outcome, "reading": after,
                         "crop": str(shots.folder / "synthetic-world.png")}

    monkeypatch.setattr(proof, "observe_step", observe)
    return env


@pytest.mark.parametrize("fight_at,control_keys,replay_keys", [
    (3, ["NP2", "NP8"], ["NP2", "NP8"]),
    (2, ["NP2", "NP8", "NP8"], ["NP2", "NP8", "NP8"]),
])
def test_one_fight_is_replayed_on_exact_move_and_off_before_cleanup(
        scenario, fight_at, control_keys, replay_keys):
    scenario.fight_at = fight_at
    result = {"verdict": "inconclusive"}
    proof.proof(scenario.shots, scenario.pipe, scenario.switch, scenario.journal,
                scenario.guest, "synthetic", lambda image: True, result)
    assert result["candidate"] is False
    assert result["diagnostic_pair"] is True
    assert result["control"][-1]["outcome"] == "combat_observation"
    assert all(step["outcome"] == "world" for step in result["replay"])
    assert scenario.shots.keys == ["L", "B", "V", "E", "B", *control_keys, *replay_keys]
    assert scenario.guest.calls == ["snapshot", "restore"]
    assert scenario.switch.calls[-1] == "off"
    assert scenario.pipe.writes == [(scenario.pipe.pointer + 0x9952, b"\x09"),
                                    (scenario.pipe.pointer + 0x9952, b"\x08")]
    assert scenario.pipe.read(scenario.pipe.pointer + 0x9952, 6) == ORIGINAL


def test_two_world_screens_never_authorize_replay(scenario):
    scenario.fight_at = 0
    result = {}
    proof.proof(scenario.shots, scenario.pipe, scenario.switch, scenario.journal,
                scenario.guest, "synthetic", lambda image: False, result)
    assert result["verdict"] == "inconclusive: no control fight in two moves"
    assert scenario.shots.keys[-3:] == ["NP2", "NP8", "NP8"]
    assert scenario.guest.calls == ["snapshot"]
    assert scenario.switch.calls == []
    assert not result.get("candidate") and not result.get("diagnostic_pair")


def test_unidentified_mode_five_is_unknown_and_cannot_replay(scenario, monkeypatch):
    scenario.fight_at = 3
    # No independent combat reference on the control frame: mode five alone is insufficient.
    old = proof.classify
    monkeypatch.setattr(proof, "classify", lambda world, combat, mode, prior, index: old(
        world, False, mode, prior, index))
    result = {}
    proof.proof(scenario.shots, scenario.pipe, scenario.switch, scenario.journal,
                scenario.guest, "synthetic", lambda image: False, result)
    assert result["verdict"] == "inconclusive: unclassified control screen"
    assert scenario.guest.calls == ["snapshot"]
    assert scenario.switch.calls == []
    assert not result.get("candidate") and not result.get("diagnostic_pair")


def test_stopped_ecl01_rejected_despite_stopped_other_area(scenario):
    scenario.switch.stopped = True
    with pytest.raises(RouteError, match="ECL01 row was stopped"):
        proof.switched({"rows": [{"row": proof.GATE, "stopped": "wrong entry"},
                                 {"row": "*0x5006+0x8739", "new": "09"}]}, scenario.pipe,
                       first=True)
    assert scenario.pipe.writes == []


def test_first_write_needs_exact_opcode_address_and_statement(scenario):
    address = scenario.pipe.pointer + 0x9952
    scenario.pipe.write(address, b"\x09")
    for reply in ({"rows": [{"row": proof.GATE, "address": address + 1, "new": "09"}]},
                  {"rows": [{"row": proof.GATE, "address": address, "new": "08"}]}):
        with pytest.raises(RouteError, match="did not write its one opcode"):
            proof.switched(reply, scenario.pipe, first=True)
    assert scenario.pipe.writes == [(address, b"\x09")]
    assert proof.switched({"rows": [{"row": proof.GATE, "address": address,
                                     "new": "09"}]}, scenario.pipe, first=True)["statement"] \
        == "09006401797f"
    scenario.pipe.cells[address] = b"\x09\x00\x64\x01\x78\x7f"
    with pytest.raises(RouteError, match="bytes differ"):
        proof.switched({"rows": []}, scenario.pipe)


def test_failed_off_cannot_restore(scenario):
    scenario.square = (4, 14, 1)
    scenario.guest.snapshot(proof.SNAPSHOT, "synthetic")
    scenario.switch.on()
    scenario.switch.fail_off = True
    with pytest.raises(RouteError, match="did not clear its journal"):
        proof.off_checked(scenario.switch, scenario.journal, scenario.pipe)
    assert scenario.guest.calls == ["snapshot"]
    assert scenario.journal.load()["on"] is True


def test_wrong_area_fix_is_rejected_before_turn(scenario):
    scenario.square = (4, 14, 1)
    result = scenario.reading()
    result["area"] = 2
    with pytest.raises(RouteError, match="not the ordinary Tilverton square"):
        proof.at_world(result, (4, 14, 1))
    result["area"] = 1
    result["fix"]["y"] = 13
    with pytest.raises(RouteError, match="not the ordinary Tilverton square"):
        proof.at_world(result, (4, 14, 1))


def test_unmeasured_control_never_becomes_combat(scenario):
    scenario.square = (4, 14, 3)
    prior = scenario.reading()
    assert proof.classify(False, False, 5, prior, 1) == "unknown"
    assert proof.classify(False, True, 4, prior, 1) == "unknown"
    assert proof.classify(True, False, 4, prior, 1) == "world"
    assert proof.classify(False, True, 5, prior, 1) == "combat_observation"
    with pytest.raises(RouteError, match="world and combat guards matched"):
        proof.classify(True, True, 5, prior, 1)


def test_wrong_entry_and_changed_operand_stop_before_walk(scenario):
    scenario.pipe.cells[scenario.pipe.pointer + 0x8000] = bytes(range(1, 21))
    with pytest.raises(RouteError, match="ECL01 pin"):
        proof.proof(scenario.shots, scenario.pipe, scenario.switch, scenario.journal,
                    scenario.guest, "synthetic", lambda image: True, {})
    assert not any(key.startswith("NP") for key in scenario.shots.keys)
    assert scenario.guest.calls == []
    scenario.pipe.cells[scenario.pipe.pointer + 0x8000] = ENTRY_BYTES
    scenario.pipe.cells[scenario.pipe.pointer + 0x9952] = b"\x08\x00\x63\x01\x79\x7f"
    scenario.shots.keys.clear()
    scenario.square = None
    with pytest.raises(RouteError, match="ECL01 pin"):
        proof.proof(scenario.shots, scenario.pipe, scenario.switch,
                    scenario.journal, scenario.guest, "synthetic", lambda image: True, {})
    assert not any(key.startswith("NP") for key in scenario.shots.keys)


def test_wrong_area_and_fix_stop_before_walk(scenario, monkeypatch):
    original = scenario.reading
    for mismatch in ("area", "fix"):
        def wrong_world(target, expected, seconds, **options):
            reading = original()
            if mismatch == "area":
                reading["area"] = 2
            else:
                reading["fix"]["x"] = 11
            proof.at_world(reading, expected)
            return reading
        monkeypatch.setattr(scenario.shots, "world_at", wrong_world)
        with pytest.raises(RouteError, match="not the ordinary Tilverton square"):
            proof.proof(scenario.shots, scenario.pipe, scenario.switch, scenario.journal,
                        scenario.guest, "synthetic", lambda image: True, {})
        assert not any(key.startswith("NP") for key in scenario.shots.keys)
        scenario.square = None
        scenario.shots.keys.clear()


def test_only_private_media_is_copied_from_generated_source(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "private"
    source.mkdir()
    destination.mkdir()
    images = {key: f"generated {key} test bytes".encode("ascii")
              for key in ("save", "diskb")}
    pins = {key: hashlib.sha256(blob).hexdigest() for key, blob in images.items()}
    for key, blob in images.items():
        (source / f"{key}.adf").write_bytes(blob)
    monkeypatch.setattr(proof, "MEDIA", pins)
    monkeypatch.setattr(proof, "SOURCE", source)
    original = {key: {"path": str(source / f"{key}.adf"), "sha256": pins[key]}
                for key in images}
    manifest = {"disks": original, "loaded_letter": "B"}
    copied = proof.private_media(manifest, destination)
    assert manifest["disks"] == original
    assert copied["loaded_letter"] == "B"
    for key, blob in images.items():
        assert (source / f"{key}.adf").read_bytes() == blob
        assert (destination / f"{key}.adf").read_bytes() == blob
        assert copied["disks"][key]["path"] == str(destination / f"{key}.adf")
        assert copied["disks"][key]["sha256"] == pins[key]
    (destination / "save.adf").write_bytes(b"different private bytes")
    assert (source / "save.adf").read_bytes() == images["save"]


def test_route_deadline_is_not_extended_by_a_capture(tmp_path):
    gallery = proof.Screens(None, "synthetic", tmp_path / "shots", None, None,
                            time.monotonic() - 1, {}, lambda: None)
    with pytest.raises(RouteError, match="cleanup time"):
        gallery.left(20)


def test_guarded_prefix_waits_out_the_previous_screen(tmp_path):
    from PIL import Image

    old = tmp_path / "generated-old.png"
    new = tmp_path / "generated-new.png"
    Image.new("RGB", (720, 568), (17, 0, 0)).save(old)
    Image.new("RGB", (720, 568), (0, 17, 0)).save(new)
    box = [0, 0, 2, 2]
    spec = tmp_path / "synthetic-guards.json"
    spec.write_text(json.dumps({"title": screen_rules.guard_rule(old, box),
                                "load_picker": screen_rules.guard_rule(new, box)}))

    class TwoFrames:
        def __init__(self):
            self.frames = [old, new]

        def grab(self, label, raw, cropped, timeout):
            data = self.frames.pop(0).read_bytes()
            raw.write_bytes(data)
            cropped.write_bytes(data)
            return True

    guest = TwoFrames()
    report = {}
    gallery = proof.Screens(guest, "synthetic", tmp_path / "shots",
                            screen_rules.PixelGuards(spec), {},
                            time.monotonic() + 2, report, lambda: None)
    assert gallery.see("load_picker", 2, from_state="title").exists()
    assert guest.frames == []
    assert len(report["events"]) == 2


def test_preflight_pins_generated_manifest_sources_and_blocks_old_mute(
        tmp_path, monkeypatch):
    source, maps, root = tmp_path / "source", tmp_path / "maps2", tmp_path / "cache"
    source.mkdir()
    maps.mkdir()
    root.mkdir()
    blobs = {key: f"generated {key}".encode("ascii") for key in ("save", "diskb")}
    pins = {key: hashlib.sha256(value).hexdigest() for key, value in blobs.items()}
    for key, value in blobs.items():
        (source / f"{key}.adf").write_bytes(value)
    original = tmp_path / "registered-original.adf"
    substitute = tmp_path / "substitute-original.adf"
    original.write_bytes(b"generated original")
    substitute.write_bytes(b"generated substitute")
    reference = tmp_path / "generated-combat-reference.png"
    reference.write_bytes(b"generated non-game reference")
    guard = {name: {"box": [0, 0, 2, 2], "sha256": "a" * 64}
             for name in ("title", "front_end", "intro", "load_picker",
                          "loaded_menu", "sheet", "world")}
    identity = {name: guard[name] for name in ("loaded_menu", "sheet")}
    (maps / "guards.json").write_text(json.dumps(guard))
    (maps / "identity.json").write_text(json.dumps(identity))
    manifest = {"title": "curse", "loaded_letter": "B",
                "state_a": {"area": 1, "x": 4, "y": 14, "facing": 1},
                "names_a": list(proof.NAMES),
                "disks": {key: {"path": str(source / f"{key}.adf"),
                                "sha256": pins[key]} for key in blobs},
                "registered": {"specimen": {
                    "path": str(original), "sha256": proof.sha256(original)}},
                "substitute": {"path": str(substitute),
                               "sha256": proof.sha256(substitute)}}
    (source / "prepare.json").write_text(json.dumps(manifest))
    args = Namespace(manifest=source / "prepare.json", guards=maps / "guards.json",
                     identity=maps / "identity.json", out=root / "proof",
                     holder="wish365-ecl01", wait_lane=0,
                     audio_proof=tmp_path / "new-mute.json")
    monkeypatch.setattr(proof, "SOURCE", source)
    monkeypatch.setattr(proof, "MEDIA", pins)
    monkeypatch.setattr(proof, "GUARDS", args.guards)
    monkeypatch.setattr(proof, "IDENTITY", args.identity)
    monkeypatch.setattr(proof, "COMBAT_REFERENCE", reference)
    monkeypatch.setattr(proof, "COMBAT_SHA256", proof.sha256(reference))
    monkeypatch.setattr(proof.scratch, "cache_dir", lambda *parts: root)
    monkeypatch.setattr(proof.WinGuest, "silence", staticmethod(lambda path: True))
    assert proof.preflight(args, Journal()) == manifest
    assert not args.out.exists()
    pending = Journal()
    pending.on = True
    pending.rows = [{"spec": proof.GATE, "original": "08", "changed": "09"}]
    with pytest.raises(RouteError, match="outstanding encounter changes"):
        proof.preflight(args, pending)
    monkeypatch.setattr(proof.WinGuest, "silence", staticmethod(lambda path: False))
    with pytest.raises(RouteError, match="fresh Windows playback mute proof"):
        proof.preflight(args, Journal())
    monkeypatch.setattr(proof.WinGuest, "silence", staticmethod(lambda path: True))
    args.holder = "other-owner"
    with pytest.raises(RouteError, match="new holder"):
        proof.preflight(args, Journal())
    args.holder = "wish365-ecl01"
    original.write_bytes(b"changed original")
    with pytest.raises(RouteError, match="provenance changed"):
        proof.preflight(args, Journal())
    original.write_bytes(b"generated original")
    (source / "save.adf").write_bytes(b"changed source")
    with pytest.raises(RouteError, match="source bytes differ"):
        proof.preflight(args, Journal())


def test_guard_miss_with_mode_five_saves_unknown_not_combat(tmp_path, monkeypatch):
    scenario = Scenario(tmp_path)
    monkeypatch.setattr(proof, "live", lambda target: scenario.reading())
    scenario.square, scenario.mode = (3, 14, 3), 5
    prior = scenario.reading()
    prior["square"] = (4, 14, 3)
    prior["mode"] = 4
    prior["fix"] = {"x": 4, "y": 14, "facing": 3, "world_map": False}

    class UnknownShots:

        def guards(self, name, crop):
            return False

        def __init__(self):
            self.captures = 0

        def left(self, cap):
            return cap

        def grab(self, label):
            self.captures += 1
            return Path("generated-unknown-frame.png")

    shots = UnknownShots()
    outcome, record = proof.observe_step(shots, scenario.pipe, 1, prior,
                                         lambda crop: False, replay=False)
    assert outcome == record["outcome"] == "unknown"
    assert shots.captures == 1
    assert record["reading"]["mode"] == 5


@pytest.mark.parametrize("fight_at,fail_off,want,restores", [
    (3, False, "inconclusive: diagnostic pair lacks verified branch witness", 2),
    (0, False, "inconclusive: no control fight in two moves", 1),
    (3, True, "inconclusive: final encounter journal is not clear", 1),
])
def test_run_halts_only_its_holder_and_checks_media_before_verdict(
        scenario, monkeypatch, tmp_path, fight_at, fail_off, want, restores):
    alarm = _windows_alarm(monkeypatch)
    scenario.fight_at = fight_at
    scenario.switch.fail_off = fail_off
    source = tmp_path / "source"
    source.mkdir()
    out = tmp_path / "private"
    originals = {key: f"synthetic {key} disk".encode("ascii")
                 for key in ("save", "diskb")}
    pins = {key: hashlib.sha256(data).hexdigest() for key, data in originals.items()}
    for key, data in originals.items():
        (source / f"{key}.adf").write_bytes(data)
    registered = tmp_path / "registered"
    registered.write_bytes(b"generated registered placeholder")
    provenance = {"path": str(registered), "sha256": proof.sha256(registered)}
    manifest = {"disks": {key: {"path": str(source / f"{key}.adf"),
                                "sha256": pins[key]} for key in originals},
                "registered": {"specimen": provenance}, "substitute": provenance,
                "title": "curse", "loaded_letter": "B", "state_a": {
                    "area": 1, "x": 4, "y": 14, "facing": 1}, "names_a": proof.NAMES}
    command_calls = []
    monkeypatch.setattr(proof, "SOURCE", source)
    monkeypatch.setattr(proof, "MEDIA", pins)
    monkeypatch.setattr(proof, "preflight", lambda args, state: manifest)
    # The synthetic entry replaces ENTRY for memory reads, not for the committed row.
    with monkeypatch.context() as committed_pins:
        committed_pins.setattr(proof, "ENTRY", "c80bfd1e")
        committed_row = proof.gate_row()
    monkeypatch.setattr(proof, "gate_row", lambda: committed_row)
    monkeypatch.setattr(proof.noencounters, "WinuaeState", lambda path: scenario.journal)
    monkeypatch.setattr(proof.screens, "canonical_file", lambda src, dst: dst.write_bytes(
        b"synthetic canonical frame"))
    monkeypatch.setattr(proof.screens, "guard_rule", lambda *a: {"sha256": "generated"})
    monkeypatch.setattr(proof, "Screens", lambda *a, **k: scenario.shots)
    monkeypatch.setattr(proof.acceptance, "boot_lane", lambda *a, **k: command_calls.append(
        ("boot", k["holder"])) or {"holder": k["holder"]})

    def halt(guest, holder, timeout, *, manifest_path, command):
        command_calls.append(("halt", holder))
        return {"holder": holder, "stop": "stopped", "release": "released",
                "fetched": {key: {"sha256": proof.sha256(
            out / f"{key}.adf")} for key in pins}}

    monkeypatch.setattr(proof.acceptance, "halt_lane", halt)
    args = Namespace(manifest=source / "prepare.json", out=out, holder="wish365-ecl01",
                     audio_proof=tmp_path / "synthetic-mute.json", wait_lane=0,
                     guards=tmp_path / "synthetic-guards.json",
                     identity=tmp_path / "synthetic-identity.json")

    def switch_factory(press):
        scenario.switch.press = press
        return scenario.switch

    report = proof.run(args, guest=scenario.guest, target=scenario.pipe,
                       switch_factory=switch_factory, guards=object(), identity=object(),
                       combat_guard=lambda crop: True)
    assert report["verdict"] == want
    assert report["branch_witness_verified"] is False
    assert report["branch_witness_reason"]
    assert json.loads((out / "summary.json").read_text())["branch_witness_reason"] \
        == report["branch_witness_reason"]
    assert report["candidate"] is False
    if alarm is not None:
        assert alarm.handler is None
        assert any(seconds > 0 for seconds in alarm.timers)
        assert alarm.timers[-1] == 0
    assert report.get("diagnostic_pair", False) is (fight_at == 3)
    assert command_calls == [("boot", args.holder), ("halt", args.holder)]
    assert scenario.guest.calls.count("snapshot") == 1
    assert scenario.guest.calls.count("restore") == restores
    assert "save" not in scenario.shots.keys and "S" not in scenario.shots.keys
    for key, original in originals.items():
        assert (source / f"{key}.adf").read_bytes() == original
        assert (out / f"{key}.adf").read_bytes() == original
    if fail_off:
        assert "did not clear its journal" in report["error"]
        assert scenario.journal.load()["on"] is True
        assert report["journal_final"]["rows"] == [{
            "spec": proof.GATE, "original": "08", "changed": "09"}]
        assert "discard" not in scenario.guest.calls
        assert report["cleanup"][0].get("off_error")
        assert "journal_error" in report["cleanup"][-1]
    else:
        assert scenario.journal.load() == {"on": False, "rows": []}
        assert scenario.guest.calls[-1] == "discard"
        assert [next(iter(step)) for step in report["cleanup"]][:4] == [
            "off", "restore", "readback", "discard"]
        assert set(report["halt"]["fetched"]) == set(pins)
        assert proof.sha256(out / "summary.json")


def test_cli_diagnostic_pair_cannot_exit_zero(monkeypatch, tmp_path, capsys):
    from contextlib import nullcontext

    report = {"verdict": "paired suppression and restoration observed",
              "candidate": True, "diagnostic_pair": True,
              "branch_witness_verified": False,
              "branch_witness_reason": "no independent live ECL01 branch witness"}
    monkeypatch.setattr(proof, "run", lambda args: report)
    monkeypatch.setattr(proof, "terminating", nullcontext)
    argv = [option for key in ("manifest", "guards", "identity", "audio-proof", "out", "holder")
            for option in (f"--{key}", str(tmp_path / f"generated-{key}"))]
    assert proof.main(argv) != 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["diagnostic_pair"] is True
    assert printed["branch_witness_verified"] is False
    assert printed["branch_witness_reason"] == report["branch_witness_reason"]


@pytest.fixture
def cleanup_run(tmp_path, monkeypatch, scenario):
    """Synthetic clock, media and lane with the real halt ordering."""
    now = [1000.0]
    monkeypatch.setattr(proof.time, "monotonic", lambda: now[0])
    alarm = _windows_alarm(monkeypatch)
    if alarm is None:
        monkeypatch.setattr(proof.signal, "setitimer", lambda *args: None)
    scenario.alarm = alarm
    source = tmp_path / "source"
    source.mkdir()
    out = tmp_path / "private"
    pins = {}
    for key in ("save", "diskb"):
        (source / f"{key}.adf").write_bytes(f"generated {key}".encode())
        pins[key] = proof.sha256(source / f"{key}.adf")
    registered = tmp_path / "generated-registered"
    registered.write_bytes(b"generated placeholder")
    entry = {"path": str(registered), "sha256": proof.sha256(registered)}
    manifest = {"disks": {key: {"path": str(source / f"{key}.adf"), "sha256": digest}
                          for key, digest in pins.items()},
                "registered": {"specimen": entry}, "substitute": entry}
    monkeypatch.setattr(proof, "SOURCE", source)
    monkeypatch.setattr(proof, "MEDIA", pins)
    monkeypatch.setattr(proof, "preflight", lambda *args: manifest)
    monkeypatch.setattr(proof, "gate_row", lambda: None)
    monkeypatch.setattr(proof.noencounters, "WinuaeState", lambda path: scenario.journal)
    monkeypatch.setattr(proof.screens, "canonical_file", lambda src, dst: dst.write_bytes(
        b"generated frame"))
    monkeypatch.setattr(proof.screens, "guard_rule", lambda *args: {"sha256": "generated"})
    monkeypatch.setattr(proof, "Screens", lambda *args: scenario.shots)
    monkeypatch.setattr(proof.acceptance, "boot_lane", lambda *a, **k: {"holder": k["holder"]})
    lane = []
    monkeypatch.setattr(proof.acceptance, "_lane_events", lambda folder, event, holder: (
        [{"remotes": {key: f"generated-{key}" for key in pins}}] if event == "boot" else []))
    monkeypatch.setattr(proof.acceptance, "_lane_log", lambda folder, data: lane.append(data))
    monkeypatch.setattr(proof.acceptance, "_entry", lambda path: {"sha256": proof.sha256(path)})
    scenario.guest.stop = lambda holder, timeout: lane.append(("stop", timeout)) or "stopped"

    def get(remote, local, timeout):
        lane.append(("get", timeout))
        local.write_bytes((source / f"{remote.split('-')[-1]}.adf").read_bytes())

    scenario.guest.get = get
    scenario.guest.release = lambda holder, timeout: lane.append(("release", timeout)) or "released"
    scenario.guest.status = lambda timeout: "no claims"
    args = Namespace(manifest=source / "prepare.json", out=out, holder="wish365-ecl01",
                     audio_proof=tmp_path / "mute", wait_lane=0,
                     guards=tmp_path / "guards", identity=tmp_path / "identity")

    def run():
        return proof.run(args, guest=scenario.guest, target=scenario.pipe,
                         switch_factory=lambda press: scenario.switch,
                         guards=object(), identity=object(), combat_guard=lambda image: True)

    return now, scenario, lane, run


def test_cleanup_off_timeout_retains_journal_and_releases_owned_lane(cleanup_run, monkeypatch):
    now, scenario, lane, run = cleanup_run

    def route(shots, target, switch, state, guest, holder, guard, report):
        scenario.square = (4, 14, 1)
        report["snapshot_attempted"] = {"holder": holder, "name": proof.SNAPSHOT}
        report["snapshot"] = guest.snapshot(proof.SNAPSHOT, holder)
        report["snapshot_taken"] = True
        switch.on()
        now[0] = 1600.0
        raise RouteError("route expired while row held")

    monkeypatch.setattr(proof, "proof", route)
    scenario.switch.off = lambda: scenario.switch.calls.append("off") or (
        now.__setitem__(0, 1751.0) or {"error": "off timed out"})
    report = run()
    assert report["error"].endswith("route expired while row held")
    if scenario.alarm is not None:
        assert scenario.alarm.handler is None
        assert any(seconds > 0 for seconds in scenario.alarm.timers)
        assert scenario.alarm.timers[-1] == 0
    assert scenario.switch.calls[-1] == "off"
    assert scenario.guest.calls == ["snapshot"]
    assert [event[0] for event in lane if isinstance(event, tuple)] == ["stop", "release"]
    assert report["journal_final"]["rows"] and report["verdict"].startswith("inconclusive")
    assert any("off_error" in event for event in report["cleanup"])
    assert any("fetch_skipped" in event for event in report["cleanup"])


def test_lost_snapshot_receipt_never_restores_but_discards_after_off(cleanup_run, monkeypatch):
    now, scenario, lane, run = cleanup_run

    def missing(name, holder):
        scenario.guest.calls.append("snapshot")
        raise RouteError("snapshot reply lost")

    scenario.guest.snapshot = missing

    def route(shots, target, switch, state, guest, holder, guard, report):
        scenario.square = (4, 14, 1)
        report["snapshot_attempted"] = {"holder": holder, "name": proof.SNAPSHOT}
        guest.snapshot(proof.SNAPSHOT, holder)

    monkeypatch.setattr(proof, "proof", route)
    report = run()
    assert report["snapshot_attempted"] == {"holder": "wish365-ecl01",
                                             "name": proof.SNAPSHOT}
    assert scenario.guest.calls == ["snapshot", "discard"]
    assert report["verdict"] == "inconclusive"
    assert [event[0] for event in lane if isinstance(event, tuple)] == [
        "stop", "get", "get", "release"]
    assert any("snapshot_error" in event for event in report["cleanup"])


def test_halt_timeouts_clip_and_release_after_failed_fetch(cleanup_run, monkeypatch):
    now, scenario, lane, run = cleanup_run

    def route(shots, target, switch, state, guest, holder, guard, report):
        scenario.square = (4, 14, 1)
        report["snapshot_attempted"] = {"holder": holder, "name": proof.SNAPSHOT}
        report["snapshot"] = guest.snapshot(proof.SNAPSHOT, holder)
        report["snapshot_taken"] = True
        now[0] = 1750.0

    monkeypatch.setattr(proof, "proof", route)

    def stop(holder, timeout):
        lane.append(("stop", timeout))
        now[0] += 30
        return "stopped"

    def get(remote, local, timeout):
        lane.append(("get", timeout))
        now[0] += 50
        raise RouteError("fetch timed out")

    scenario.guest.stop, scenario.guest.get = stop, get
    report = run()
    assert [event[0] for event in lane if isinstance(event, tuple)] == [
        "stop", "get", "get", "release"]
    assert lane[0][1] >= lane[1][1] > lane[2][1] > 0
    assert report["verdict"] == "inconclusive"
    assert any("halt_error" in event for event in report["cleanup"])


def test_failed_release_and_status_leave_holder_unresolved(cleanup_run, monkeypatch):
    now, scenario, lane, run = cleanup_run

    def route(shots, target, switch, state, guest, holder, guard, report):
        scenario.square = (4, 14, 1)
        now[0] = 1760.0
        raise RouteError("route failed before snapshot")

    def release(holder, timeout):
        lane.append(("release", timeout))
        raise RouteError("release receipt lost")

    scenario.guest.release = release
    scenario.guest.status = lambda timeout: (_ for _ in ()).throw(RouteError("status lost"))
    monkeypatch.setattr(proof, "proof", route)
    report = run()
    assert report["error"].endswith("route failed before snapshot")
    assert [event[0] for event in lane if isinstance(event, tuple)] == ["stop", "release"]
    assert report["holder_unresolved"] is True
    assert "release receipt lost" in str(report["cleanup"])
    assert "status lost" in str(report["cleanup"])
    assert report["verdict"] == "inconclusive"


@pytest.mark.parametrize("failure", ["restore", "readback", "journal"])
def test_unverified_snapshot_is_retained_while_owned_lane_stops(
        cleanup_run, monkeypatch, failure):
    now, scenario, lane, run = cleanup_run

    def route(shots, target, switch, state, guest, holder, guard, report):
        scenario.square = (4, 14, 1)
        report["snapshot_attempted"] = {"holder": holder, "name": proof.SNAPSHOT}
        report["snapshot"] = guest.snapshot(proof.SNAPSHOT, holder)
        report["snapshot_taken"] = True
        now[0] = 1700.0

    monkeypatch.setattr(proof, "proof", route)
    if failure == "restore":
        scenario.guest.restore = lambda name, holder: scenario.guest.calls.append(
            "restore") or (_ for _ in ()).throw(RouteError("state file missing"))
    elif failure == "readback":
        original_pinned = proof.pinned
        counts = [0]

        def failed_readback(target, expected):
            counts[0] += 1
            if counts[0] == 2:
                raise RouteError("original statement readback lost")
            return original_pinned(target, expected)

        monkeypatch.setattr(proof, "pinned", failed_readback)
    else:
        original_load = scenario.journal.load
        counts = [0]

        def failed_journal():
            counts[0] += 1
            if counts[0] == 4:
                raise RouteError("journal readback lost")
            return original_load()

        monkeypatch.setattr(scenario.journal, "load", failed_journal)
    report = run()
    assert scenario.guest.calls == ["snapshot", "restore"]
    assert report["snapshot_unresolved"] == {
        "holder": "wish365-ecl01", "name": proof.SNAPSHOT,
        "exists": None, "discard_attempted": False}
    assert [event[0] for event in lane if isinstance(event, tuple)] == [
        "stop", "get", "get", "release"]
    assert any("snapshot_error" in event for event in report["cleanup"])
    assert report["verdict"] == "inconclusive"


FOUR_CLAIMS = ("lanes = 4\nclaim = none\nclaim 2 = other since 2026-10-11\n"
               "claim 3 = none\nclaim 4 = none")


@pytest.mark.parametrize("reply", [
    "", "no claims", "claim = none", "lanes = 3\n" + FOUR_CLAIMS,
    FOUR_CLAIMS.replace("claim 4 = none", ""),
    FOUR_CLAIMS + "\nclaim 4 = none",
    FOUR_CLAIMS.replace("claim 3 = none", "claim 3 = none since yesterday"),
    FOUR_CLAIMS.replace("claim 3 = none", "claim 3 = other"),
    FOUR_CLAIMS.replace("claim 3 = none", "claim 5 = none"),
    FOUR_CLAIMS + "\nclaim: wish365-ecl01 since yesterday",
    FOUR_CLAIMS + "\nclaims: wish365-ecl01 since yesterday",
    FOUR_CLAIMS + "\nclaim? broken guest claim",
])
def test_lost_release_with_incomplete_guest_status_cannot_resolve_holder(
        cleanup_run, monkeypatch, reply):
    now, scenario, lane, run = cleanup_run

    def route(shots, target, switch, state, guest, holder, guard, report):
        scenario.square = (4, 14, 1)
        now[0] = 1760.0
        raise RouteError("route fault")

    monkeypatch.setattr(proof, "proof", route)
    scenario.guest.release = lambda holder, timeout: (_ for _ in ()).throw(
        RouteError("release reply lost"))
    scenario.guest.status = lambda timeout: reply
    report = run()
    assert report["error"].endswith("route fault")
    assert report["holder_status"] == reply
    assert report["holder_unresolved"] is True
    assert any("status_error" in item for item in report["cleanup"])
    assert report["verdict"] == "inconclusive"


@pytest.mark.parametrize("held", [False, True])
def test_complete_status_checks_exact_claim_not_unrelated_diagnostics(
        cleanup_run, monkeypatch, held):
    now, scenario, lane, run = cleanup_run

    def route(shots, target, switch, state, guest, holder, guard, report):
        scenario.square = (4, 14, 1)
        now[0] = 1760.0
        raise RouteError("route fault")

    monkeypatch.setattr(proof, "proof", route)
    scenario.guest.release = lambda holder, timeout: (_ for _ in ()).throw(
        RouteError("release reply lost"))
    status = FOUR_CLAIMS.replace("claim 3 = none", (
        "claim 3 = wish365-ecl01 since yesterday" if held else "claim 3 = none"))
    if not held:
        status += "\nrun = wish365-ecl01 appears only in diagnostics"
    scenario.guest.status = lambda timeout: status
    report = run()
    assert report["holder_status"] == status
    assert report["holder_unresolved"] is held
    assert not any("status_error" in item for item in report["cleanup"])
    assert any("halt_error" in item for item in report["cleanup"])
    assert report["verdict"] == "inconclusive"
