"""The seven-member source-G Return and reload phases, on generated media and fakes only."""

from __future__ import annotations

import hashlib
import json
import pathlib
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from tests.amiga.test_darknessreturn import _seven_source, _synthetic_private_files
from tools.amiga import darknessreturn as driver
from tools.amiga.staging import sha256
from tools.amiga.winuaesession import RouteError

FORBIDDEN_BEFORE_SAVE = {"S", "F", "G"}


def _relocate_case_children(generated, base: int) -> None:
    """Move HILDE's four children to new allocations, as a reload or rejoin would."""
    old = sorted(generated.children)
    for ordinal, (_, raw) in enumerate(old):
        child = bytearray(raw)
        child[0x42:0x46] = (base + (ordinal + 1) * 0x80 if ordinal < 3 else 0).to_bytes(4, "big")
        generated.target.put(base + ordinal * 0x80, bytes(child))
    generated.target.put(generated.case + 0x42, base.to_bytes(4, "big"))


def test_case_head_first_child_link_is_compared_across_checkpoints(tmp_path, monkeypatch):
    _synthetic_private_files(monkeypatch, tmp_path)
    generated = _seven_source(tmp_path, monkeypatch)
    _, entry = generated.capture()
    earlier = json.loads(generated.path.read_text())
    generated.path.unlink()
    _relocate_case_children(generated, 0x9000)
    reading, entry = generated.capture()
    digest = hashlib.sha256(generated.saved).hexdigest()
    report = driver._source_compare(entry, reading, generated.disk, "F", digest,
                                    generated.root, role="same-run-F", previous=earlier)
    assert report["all_payloads_match_reference"]
    links = [row for row in report["metadata_differences"] if "case_link_offsets" in row]
    assert links == [{"slot": 4, "head": 2, "case_link_offsets": [0x44]}]
    children = [row for row in report["metadata_differences"] if "child" in row]
    # The last child keeps its NULL link, so only the three relinked children differ.
    assert [row["child"] for row in children] == [0, 1, 2]
    # The child's +0x2a bytes keep their existing label and gain no new one.
    assert all(set(row) == {"slot", "head", "child", "display_offsets", "stale_link_offsets",
                            "payload_offsets", "child_link_offsets"} for row in children)
    assert all(row["child_link_offsets"] for row in children)
    assert all(not row["payload_offsets"] for row in children)


def test_unchanged_case_link_reports_no_case_link_difference(tmp_path, monkeypatch):
    _synthetic_private_files(monkeypatch, tmp_path)
    generated = _seven_source(tmp_path, monkeypatch)
    _, entry = generated.capture()
    earlier = json.loads(generated.path.read_text())
    generated.path.unlink()
    reading, entry = generated.capture()
    digest = hashlib.sha256(generated.saved).hexdigest()
    report = driver._source_compare(entry, reading, generated.disk, "F", digest,
                                    generated.root, role="same-run-F", previous=earlier)
    assert report["metadata_differences"] == []


@pytest.mark.parametrize("letter, digest_kind, role, ok", [
    ("G", "pinned-g", "origin-source-G", True),
    ("G", "other", "origin-source-G", False),
    ("F", "pinned-g", "origin-source-G", False),
    ("F", "other", "return-new-F", True),
    ("G", "other", "return-new-F", False),
    ("F", "other", "reload-F", True),
    ("G", "other", "reload-F", False),
    ("F", "other", "selected-source", False),
    ("F", "other", "new-F", False),
])
def test_source_g_new_f_and_reload_labels_bind_their_own_letters(
        tmp_path, monkeypatch, letter, digest_kind, role, ok):
    _synthetic_private_files(monkeypatch, tmp_path)
    generated = _seven_source(tmp_path, monkeypatch)
    reading, entry = generated.capture()
    digest = hashlib.sha256(generated.saved).hexdigest()
    monkeypatch.setattr(driver, "ORIGIN_G_SHA256", digest if digest_kind == "pinned-g"
                        else "0" * 64)
    monkeypatch.setattr(driver, "BUNDLE_SOURCE_F_SHA256", "1" * 64)
    if ok:
        report = driver._source_compare(entry, reading, generated.disk, letter, digest,
                                        generated.root, role=role)
        assert report["reference_role"] == role and report["reference_letter"] == letter
        assert report["preservation_established"] is False
    else:
        with pytest.raises(RouteError, match="bundle_source_reference"):
            driver._source_compare(entry, reading, generated.disk, letter, digest,
                                   generated.root, role=role)


def _leg(seen, keys=(), result="idle", settled=True):
    return {"result": result, "settled": settled, "areas_seen": list(seen),
            "arrival_keys": list(keys)}


def _trip_log(path, legs, *, guard=True, drop=False):
    """The Fast Travel driver's JSON lines: one legality per leg, then its arrival answers."""
    lines = []
    for leg in legs:
        lines.append({"event": "legality", "ok": True})
        if not drop:
            lines += [{"event": "arrival_answer", "key": key, "at_continue": guard}
                      for key in leg.get("arrival_keys", [])]
        lines.append({"event": "settle", "gate": True})
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


@pytest.mark.parametrize("legs, ok", [
    ([_leg([82, 22], ["RET"]), _leg([22, 82])], True),
    ([_leg([82, 0, 22]), _leg([22, 0, 82])], True),
    # Kalistes' Parlor opens on the same PRESS RETURN bar as Taydome's Keep.
    ([_leg([82, 22], ["RET"]), _leg([22, 82], ["RET"])], True),
    ([_leg([82, 22]), _leg([22, 82], ["RET"])], True),
    ([_leg([5, 22], ["RET"]), _leg([22, 5])], False),
    ([_leg([17, 22], ["RET"]), _leg([22, 17])], False),
    ([_leg([82, 22], ["RET"]), _leg([22, 17])], False),
    ([_leg([82, 23]), _leg([23, 82])], False),
    ([_leg([82, 22], ["RET"]), _leg([22, 82], ["RET", "RET"])], False),
    ([_leg([82, 22], ["Y"]), _leg([22, 82])], False),
    ([_leg([82, 22]), _leg([22, 82], ["N"])], False),
    ([_leg([82, 22], ["RET", "RET"]), _leg([22, 82])], False),
    ([_leg([82, 22], settled=False), _leg([22, 82])], False),
    ([_leg([82, 22]), _leg([22], result="not_legal")], False),
    ([_leg([82, 22])], False),
])
def test_origin_legs_require_82_to_22_and_back_with_only_the_guarded_arrival_key(
        tmp_path, legs, ok):
    log = _trip_log(tmp_path / "fasttravel.jsonl", legs)
    if ok:
        assert driver._origin_legs(legs, log) == legs
    else:
        with pytest.raises(RouteError, match="return7_"):
            driver._origin_legs(legs, log)


@pytest.mark.parametrize("damage", ["unguarded", "unlogged", "missing", "one-leg"])
def test_an_arrival_ret_counts_only_when_the_log_shows_the_continue_guard_matched(
        tmp_path, damage):
    legs = [_leg([82, 22], ["RET"]), _leg([22, 82], ["RET"])]
    log = tmp_path / "fasttravel.jsonl"
    if damage == "unguarded":
        _trip_log(log, legs, guard=False)
    elif damage == "unlogged":
        _trip_log(log, legs, drop=True)
    elif damage == "one-leg":
        _trip_log(log, legs[:1])
    with pytest.raises(RouteError, match="return7_prompt"):
        driver._origin_legs(legs, log)


@pytest.mark.parametrize("live, gate, offered, square, ok", [
    (82, True, True, (3, 10, 3), True),
    (5, True, True, (3, 10, 3), False),
    (82, False, True, (3, 10, 3), False),
    (82, True, False, (3, 10, 3), False),
    (82, True, True, None, False),
])
def test_origin_start_checks_live_area_gate_and_ordinary_legality(
        tmp_path, monkeypatch, live, gate, offered, square, ok):
    calls = []

    def observe(target, *, saved_area, disks):
        calls.append((saved_area, disks))
        return {"saved_area": saved_area, "live_area": live, "gate": gate,
                "target_area": 22, "offered": offered, "reason": "" if offered else "held"}

    monkeypatch.setattr(driver, "_observe_origin", observe)
    monkeypatch.setattr(driver.amigatrip, "square", lambda target, row: square)
    if ok:
        got = driver._origin_start(object(), tmp_path)
        assert got["square"] == [3, 10, 3] and got["live_area"] == 82
    else:
        with pytest.raises(RouteError, match="return7_start"):
            driver._origin_start(object(), tmp_path)
    assert calls == [(5, tmp_path)]


@pytest.mark.parametrize("live, gate, square, ok", [
    (82, True, (3, 10, 3), True), (22, True, (3, 10, 3), False),
    (82, False, (3, 10, 3), False), (82, True, None, False),
])
def test_origin_place_requires_the_party_back_in_82_at_the_menu(monkeypatch, live, gate,
                                                                square, ok):
    monkeypatch.setattr(driver.amigatrip, "area_id", lambda target, row: live)
    monkeypatch.setattr(driver.amigatrip, "gate", lambda target, row: gate)
    monkeypatch.setattr(driver.amigatrip, "square", lambda target, row: square)
    if ok:
        assert driver._origin_place(object(), "return7") == {
            "live_area": 82, "gate": True, "square": [3, 10, 3]}
    else:
        with pytest.raises(RouteError, match="return7_"):
            driver._origin_place(object(), "return7")


class _Guest:
    """Records every lane operation the phases make; fetches write generated bytes."""

    def __init__(self, events, remotes, contents=None):
        self.events, self.remotes = events, remotes
        # What each fetched disk holds: a callable per key, or the generated marker.
        self.contents = contents or {}
        self.stop_fails = False

    def insert(self, holder, drive, remote, timeout, sha256):
        self.events.append(("insert", drive))

    def press(self, *args, **kwargs):
        pytest.fail("A phase bypassed its guarded run")

    def snapshot(self, name, holder):
        self.events.append(("snapshot", name))

    def discard(self, name, holder):
        self.events.append(("discard", name))

    def stop(self, holder, timeout):
        self.events.append(("stop", holder, timeout))
        if self.stop_fails:
            raise RouteError("injected stop failure")
        return "stopped"

    def get(self, remote, local, timeout):
        key = next(key for key, value in self.remotes.items() if value == remote)
        self.events.append(("fetch", key))
        local.write_bytes(self.contents[key]() if key in self.contents
                          else f"Generated fetched {key} marker".encode())
        return "fetched"

    def release(self, holder, timeout):
        self.events.append(("release", holder))
        return "released"


class _Run:
    def __init__(self, events, fail):
        self.events_log, self.fail, self.events = events, fail, []

    def see(self, state, limit=None):
        self.events_log.append(("screen", state))
        self.events.append({"screen": state, "shot": len(self.events) + 1, "time": 1.0})

    def title(self):
        self.see("title")

    def press(self, state, key, following=None):
        self.see(state)
        self.events_log.append(("key", key))
        self.events.append({"key": key, "from": state, "time": 1.0})
        if following is not None:
            self.see(following)


def _common(monkeypatch, events, comparisons, fail, mismatch):
    def checkpoint(target, directory, phase, receipt, run, disk_hash, *, screens, reference):
        events.append(("checkpoint", phase, screens, tuple(sorted(reference))))
        assert run.events[-1]["screen"] in screens
        if fail == f"capture-{phase}":
            raise RouteError("bundle_source_capture: 64 heads and four children are required")
        receipt.setdefault("item_nodes", []).append({"checkpoint": phase})
        return {"party": [{"name": name} for name in driver.BUNDLE_NAMES]}

    def compare(entry, reading, disk, letter, digest, root, *, role, previous=None):
        comparisons.append((entry["checkpoint"], letter, role, previous is not None))
        events.append(("compare", entry["checkpoint"], role))
        match = (entry["checkpoint"], role) != mismatch
        return {"all_payloads_match_reference": match,
                "evidence_status": "capture_coverage_complete" if match else "payload_mismatch",
                "independently_authenticated": False, "preservation_established": False}

    def boot(guest, manifest_path, manifest, holder, proof, deadline, command):
        events.append(("boot", holder, command[1]))
        return {"holder": holder, "claim": "ok", "start": "ok",
                "remotes": {key: f"remote-{key}" for key in ("disk1", "disk2", "disk3")}}

    monkeypatch.setattr(driver, "_source_checkpoint", checkpoint)
    monkeypatch.setattr(driver, "_source_compare", compare)
    monkeypatch.setattr(driver, "_source_saved_artifact", lambda *a: {"items": []})
    monkeypatch.setattr(driver, "_boot", boot)
    monkeypatch.setattr(driver, "_target", lambda holder: object())
    monkeypatch.setattr(driver, "SourceGuardedRun",
                        lambda *a, **kw: _Run(events, fail))
    monkeypatch.setattr(driver, "_origin_party", lambda target: (
        events.append(("party",)) or {"names": list(driver.BUNDLE_NAMES)}))
    monkeypatch.setattr(driver, "run_p2", lambda *a, **kw: pytest.fail("A seven-member phase used P2"))
    monkeypatch.setattr(driver, "run_reload", lambda *a, **kw: pytest.fail("A seven-member phase used reload"))


def _return_coordinator(tmp_path, monkeypatch, *, fail=None, mismatch=None):
    private_path = _synthetic_private_files(monkeypatch, tmp_path)
    root = private_path(tmp_path / ".cache/wish/acceptance/360/synthetic-origin")
    root.mkdir(parents=True, mode=0o700)
    original = root / "immutable-source.adf"
    original.write_bytes(b"Generated immutable source marker")
    disks = {}
    for key in ("disk1", "disk2", "disk3"):
        path = root / f"{key}.adf"
        path.write_bytes(f"Generated {key} marker".encode())
        path.chmod(0o600)
        disks[key] = {"path": str(path), "sha256": sha256(path)}
    manifest = root / "prepare.json"
    manifest.write_text(json.dumps({"title": "darkness", "loaded_letter": "B", "disks": disks}))
    manifest.chmod(0o600)
    controls = root / "source-controls.json"
    controls.write_text("{}")
    events, comparisons = [], []
    _common(monkeypatch, events, comparisons, fail, mismatch)
    monkeypatch.setattr(driver.pathlib.Path, "home", lambda: private_path(tmp_path))
    monkeypatch.setattr(driver, "_origin_contract", lambda path, data: (
        original, disks["disk3"]["sha256"]))
    monkeypatch.setattr(driver, "_origin_controls", lambda *a: (
        None, None, {"guards": {"sha256": "generated"}, "identity": {"sha256": "generated"}}))
    monkeypatch.setattr(driver, "_origin_source", lambda: original)
    monkeypatch.setattr(driver, "ORIGIN_IMAGE_SHA256", sha256(original))
    for key in ("disk1", "disk2"):
        monkeypatch.setattr(driver.route_darkness, f"DARKNESS_{key.upper()}_SHA256",
                            disks[key]["sha256"])

    def start(target, disks_dir):
        events.append(("start", disks_dir))
        if fail == "start":
            raise RouteError("return7_start: live area 5 is not 82")
        return {"live_area": 82, "gate": True, "offered": True, "square": [3, 10, 3]}

    def place(target, stage):
        events.append(("place", stage))
        if fail == "returned":
            raise RouteError("return7_area: the party is in area 22, not 82")
        # The game's foyer square, or the departure square Return wrote before area 82's init.
        return {"live_area": 82, "gate": True,
                "square": [3, 10, 3] if fail == "moved" else [7, 15, 0]}

    def trip(holder, disks_dir, out, left):
        events.append(("trip", holder))
        assert left <= 2000
        legs = [{"result": "idle", "settled": True, "areas_seen": [82, 22],
                 "arrival_keys": ["RET"]},
                {"result": "idle", "settled": True,
                 "areas_seen": [22, 17 if fail == "trip-area" else 82], "arrival_keys": ["RET"]}]
        out.mkdir()
        _trip_log(out / "fasttravel.jsonl", legs, guard=fail != "unguarded-return")
        return legs

    saved_f = b"Generated game-written F"

    def fetched(guest, remote, out, limit, *, place):
        events.append(("readback", remote, place))
        return SimpleNamespace(kind="f"), hashlib.sha256(saved_f).hexdigest()

    class Disk:
        def verify(self):
            return []

    monkeypatch.setattr(driver, "_origin_start", start)
    monkeypatch.setattr(driver, "_origin_place", place)
    monkeypatch.setattr(driver, "_run_trip", trip)
    monkeypatch.setattr(driver, "_source_fetched", fetched)
    monkeypatch.setattr(driver.amiga_adf.AmigaDisk, "open", lambda path: Disk())
    monkeypatch.setattr(driver.amiga_savegame, "pod_read_slot", lambda disk, letter: saved_f)
    monkeypatch.setattr(driver.route_darkness, "DARKNESS", SimpleNamespace(
        slot_letters=lambda disk: ["B", "F"],
        read_slot=lambda disk, letter: {"place": {
            "area": 5, "x": 3 if fail == "moved" else 7, "y": 10 if fail == "moved" else 15,
            "facing": 2 if fail == "saved-place" else 3 if fail == "moved" else 0}}))
    guest = _Guest(events, {key: f"remote-{key}" for key in disks})
    args = SimpleNamespace(run_id="synthetic-origin", holder="return7-holder", budget=3000,
                           out=root / "return-output-01", manifest=manifest, controls=controls,
                           source_manifest=root / "source-prepare.json",
                           audio_proof=root / "audio.json")
    return args, guest, events, comparisons, original, disks


def _keys(events):
    return [event[1] for event in events if event[0] == "key"]


def test_return_phase_captures_before_travel_and_before_new_f_then_compares_to_that_f(
        tmp_path, monkeypatch):
    args, guest, events, comparisons, original, disks = _return_coordinator(tmp_path, monkeypatch)
    originals = {path: sha256(path) for path in
                 (original, *(pathlib.Path(item["path"]) for item in disks.values()))}
    receipt = driver.run_origin_return(args, guest=guest)
    assert receipt["success"] is True
    assert "previous_return_attempts" not in receipt
    checkpoints = [event[1] for event in events if event[0] == "checkpoint"]
    assert checkpoints == ["pre-travel", "post-return", "pre-f", "post-f"]
    assert [event[2] for event in events if event[0] == "checkpoint"] == [
        ("world",), ("world",), ("camp_save_picker",), ("camp",)]
    assert all(event[3] == ("source_disk_sha256", "source_g_sha256")
               for event in events if event[0] == "checkpoint")
    assert comparisons == [("pre-travel", "G", "origin-source-G", False),
                           ("post-return", "G", "origin-source-G", True),
                           ("pre-f", "G", "origin-source-G", True),
                           ("pre-f", "F", "return-new-F", False),
                           ("post-f", "F", "return-new-F", True)]
    order = [event[0] if event[0] != "key" else event[1] for event in events]
    assert events.index(("compare", "pre-travel", "origin-source-G")) < order.index("trip")
    assert order.index("trip") < order.index("place")
    assert events.index(("compare", "pre-f", "origin-source-G")) < order.index("F")
    assert _keys(events).count("F") == 1 and "G" not in _keys(events)
    # Nothing restores a snapshot in this one-boot phase, so none is taken.
    assert "snapshot" not in order and "discard" not in order
    assert order.index("stop") < order.index("release")
    assert [event for event in events if event[0] == "fetch"] == [
        ("fetch", "disk1"), ("fetch", "disk2"), ("fetch", "disk3")]
    assert ("readback", "remote-disk3", None) in events
    assert [event for event in events if event[0] == "boot"] == [
        ("boot", "return7-holder", "origin-return")]
    path = args.out / "origin-return-receipt.json"
    stored = json.loads(path.read_text())
    assert stored["success"] is True
    assert stored["independently_authenticated"] is False
    assert stored["preservation_established"] is False
    assert stored["return_square_matches_start"] is False
    assert stored["return_square_expected"] == [7, 15, 0]
    assert stored["return_square_matches_arrival"] is True
    assert stored["checks"]["return_square"] is True
    assert stored["halt"]["fetched"]["disk3"]["path"] == "return-output-01/fetched/fetched-disk3.adf"
    assert "raw_hex" not in path.read_text()
    assert {path: sha256(path) for path in originals} == originals


@pytest.mark.parametrize("fail, mismatch, travelled, saved", [
    ("start", None, False, False),
    (None, ("pre-travel", "origin-source-G"), False, False),
    ("capture-pre-travel", None, False, False),
    ("trip-area", None, True, False),
    ("unguarded-return", None, True, False),
    ("returned", None, True, False),
    (None, ("post-return", "origin-source-G"), True, False),
    ("capture-pre-f", None, True, False),
    (None, ("pre-f", "origin-source-G"), True, False),
    ("saved-place", None, True, True),
    (None, ("pre-f", "return-new-F"), True, True),
    (None, ("post-f", "return-new-F"), True, True),
])
def test_return_phase_stops_before_travel_or_save_and_always_releases_its_lane(
        tmp_path, monkeypatch, fail, mismatch, travelled, saved):
    args, guest, events, _, _, _ = _return_coordinator(
        tmp_path, monkeypatch, fail=fail, mismatch=mismatch)
    with pytest.raises(RouteError):
        driver.run_origin_return(args, guest=guest)
    receipt = json.loads((args.out / "origin-return-receipt.json").read_text())
    assert receipt["success"] is False and receipt["error"]
    assert (("trip", args.holder) in events) is travelled
    assert (_keys(events).count("F") == 1) is saved
    assert "G" not in _keys(events)
    assert events[-1] == ("release", args.holder)
    assert not [event for event in events if event[0] in ("snapshot", "discard")]
    assert receipt["checks"].get("source_unchanged") is True
    assert receipt["checks"].get("prepared_unchanged") is True


@pytest.mark.parametrize("budget", [1800, 3601])
def test_return_phase_budget_is_bounded_before_any_output(tmp_path, monkeypatch, budget):
    args, guest, events, _, _, _ = _return_coordinator(tmp_path, monkeypatch)
    args.budget = budget
    with pytest.raises(RouteError, match="return7_deadline"):
        driver.run_origin_return(args, guest=guest)
    assert not args.out.exists() and not events


def test_return_phase_needs_no_previous_return_attempt_count(tmp_path, monkeypatch, capsys):
    called = []
    monkeypatch.setattr(driver, "run_origin_return", lambda args: called.append(args) or {
        "success": True, "checks": {"halt": True},
        "post_f_comparison": {"evidence_status": "capture_coverage_complete"}})
    monkeypatch.setattr(driver, "run_p2", lambda *a: pytest.fail("Return used P2"))
    monkeypatch.setattr(driver, "terminating", nullcontext)
    out = tmp_path / "return-output-01"
    command = ["origin-return", "--run-id", "generated-origin", "--holder", "generated-holder",
               "--audio-proof", str(tmp_path / "audio.json"),
               "--manifest", str(tmp_path / "prepare.json"),
               "--source-manifest", str(tmp_path / "source-prepare.json"),
               "--controls", str(tmp_path / "controls.json"),
               "--out", str(out), "--budget", "3000"]
    assert driver.main(command) == 0
    assert len(called) == 1 and not hasattr(called[0], "previous_return_attempts")
    report = json.loads(capsys.readouterr().out)
    assert report["receipt"] == str(out / "origin-return-receipt.json")
    assert report["comparisons"] == {"post_f_comparison": "capture_coverage_complete"}
    assert report["preservation_established"] is False
    with pytest.raises(SystemExit):
        driver.main(["origin-reload", *command[1:]])


def _return_receipt(path: pathlib.Path, *, damage=None) -> dict:
    receipt = {"phase": "origin-return", "success": True, "cleanup": [],
               "checks": {key: True for key in driver.RETURN_CHECKS},
               "same_run_f_sha256": "f" * 64, "final_f_sha256": "f" * 64,
               "halt": {"fetched": {"disk3": {"path": "return-output-01/fetched/fetched-disk3.adf",
                                               "sha256": None}}},
               "item_nodes": [{"checkpoint": "post-f"}],
               "saved_place": {"area": 5, "x": 3, "y": 10, "facing": 3},
               "returned": {"square": [3, 10, 3]},
               "source_g_sha256": driver.ORIGIN_G_SHA256,
               "source_image_sha256": driver.ORIGIN_IMAGE_SHA256}
    if damage == "source-g":
        receipt["source_g_sha256"] = driver.BUNDLE_SOURCE_F_SHA256
    if damage == "source-image":
        receipt["source_image_sha256"] = driver.BUNDLE_IMAGE_SHA256
    if damage == "failed":
        receipt["success"] = False
    if damage == "check":
        receipt["checks"]["post_f_alignment"] = False
    if damage == "readback":
        receipt["final_f_sha256"] = "e" * 64
    if damage == "escape":
        receipt["halt"]["fetched"]["disk3"]["path"] = "../elsewhere.adf"
    return receipt


@pytest.mark.parametrize("damage", [None, "failed", "check", "readback", "escape", "phase",
                                    "disk", "slot", "source-g", "source-image"])
def test_reload_seed_takes_only_a_complete_return_receipt_and_its_own_f(
        tmp_path, monkeypatch, damage):
    tmp_path = _synthetic_private_files(monkeypatch, tmp_path)(tmp_path)
    out = tmp_path / "run" / "return-output-01"
    (out / "fetched").mkdir(parents=True)
    disk = out / "fetched" / "fetched-disk3.adf"
    disk.write_bytes(b"Generated fetched disk 3")
    receipt = _return_receipt(out, damage=damage)
    receipt["halt"]["fetched"]["disk3"]["sha256"] = (
        "0" * 64 if damage == "disk" else sha256(disk))
    if damage == "phase":
        receipt["phase"] = "origin-observe"
    path = out / "origin-return-receipt.json"
    path.write_text(json.dumps(receipt))
    path.chmod(0o600)

    class Disk:
        def verify(self):
            return []

    monkeypatch.setattr(driver.amiga_adf.AmigaDisk, "open", lambda p: Disk())

    def slot(disk, letter, digest):
        assert (letter, digest) == ("F", "f" * 64)
        if damage == "slot":
            raise RouteError("bundle_source_f: slot digest differs")
        return b"", None

    monkeypatch.setattr(driver, "_source_slot", slot)
    if damage is None:
        seed = driver._return_seed(path)
        assert seed["disk"] == disk and seed["f_sha256"] == "f" * 64
        assert seed["post_f"] == {"checkpoint": "post-f"} and seed["out"] == out
    else:
        with pytest.raises(RouteError, match="reload7_"):
            driver._return_seed(path)


def _reload_coordinator(tmp_path, monkeypatch, *, fail=None, mismatch=None, changed_b=False):
    private_path = _synthetic_private_files(monkeypatch, tmp_path)
    home = private_path(tmp_path)
    root = home / ".cache/wish/acceptance/360/synthetic-reload"
    seed_dir = home / "seed"
    seed_dir.mkdir()
    seed_disk = seed_dir / "fetched-disk3.adf"
    seed_disk.write_bytes(b"Generated Return disk 3")
    original = seed_dir / "immutable-source.adf"
    original.write_bytes(b"Generated immutable source marker")
    receipt_path = seed_dir / "origin-return-receipt.json"
    receipt_path.write_text("{}")
    (seed_dir / "controls.json").write_text("{}")
    events, comparisons = [], []
    _common(monkeypatch, events, comparisons, fail, mismatch)
    monkeypatch.setattr(driver.pathlib.Path, "home", lambda: home)
    seed = {"disk": seed_disk, "disk_sha256": sha256(seed_disk), "f_sha256": "f" * 64,
            "post_f": {"checkpoint": "post-f"}, "out": seed_dir,
            "place": {"area": 5, "x": 3, "y": 10, "facing": 3}, "square": [3, 10, 3]}
    monkeypatch.setattr(driver, "_return_seed", lambda path: events.append(("seed",)) or seed)
    disks = {}

    def prepare(title, run_id, *, substitute, substitute_letter, issue):
        events.append(("prepare", run_id, substitute, substitute_letter, issue))
        root.mkdir(parents=True, mode=0o700)
        for key in ("disk1", "disk2", "disk3"):
            path = root / f"{key}.adf"
            path.write_bytes(f"Generated {key} marker".encode())
            disks[key] = {"path": str(path), "sha256": sha256(path)}
            monkeypatch.setattr(driver.route_darkness, f"DARKNESS_{key.upper()}_SHA256",
                                disks[key]["sha256"])
        manifest = root / "prepare.json"
        manifest.write_text(json.dumps({"disks": disks}))
        return manifest

    monkeypatch.setattr(driver.acceptance, "prepare", prepare)
    monkeypatch.setattr(driver, "_reload_contract", lambda path, data, got: (
        events.append(("contract", got is seed)) or disks["disk3"]["sha256"]))
    monkeypatch.setattr(driver, "_reload_controls", lambda *a: (
        None, None, {"guards": {"sha256": "generated"}, "identity": {"sha256": "generated"}}))
    monkeypatch.setattr(driver, "_origin_source", lambda: original)
    monkeypatch.setattr(driver, "ORIGIN_IMAGE_SHA256", sha256(original))
    monkeypatch.setattr(driver, "_origin_place", lambda target, stage: (
        events.append(("place", stage)) or {"live_area": 82, "gate": True,
                                            "square": [3, 9 if fail == "elsewhere" else 10, 3]}))
    monkeypatch.setattr(driver.amiga_adf.AmigaDisk, "open", lambda path: SimpleNamespace(
        path=str(path)))
    monkeypatch.setattr(driver.route_darkness, "DARKNESS", SimpleNamespace(
        slot_letters=lambda disk: pytest.fail("A slot list stood in for the whole-disk check")))

    def ran_disk3():
        # The emulator's disk 3 is the uploaded prepared copy, or that copy with slot B changed.
        data = bytearray((root / "disk3.adf").read_bytes())
        if changed_b:
            data[-1] ^= 1
        return bytes(data)

    guest = _Guest(events, {key: f"remote-{key}" for key in ("disk1", "disk2", "disk3")},
                   contents={"disk3": ran_disk3})
    args = SimpleNamespace(run_id="synthetic-reload", holder="reload7-holder", budget=1500,
                           out=root / "reload-output-01", return_receipt=receipt_path,
                           controls=seed_dir / "controls.json",
                           source_manifest=seed_dir / "source-prepare.json",
                           audio_proof=seed_dir / "audio.json")
    return args, guest, events, comparisons


def test_reload_phase_loads_new_f_views_sheet_and_hildes_items_without_saving(
        tmp_path, monkeypatch):
    args, guest, events, comparisons = _reload_coordinator(tmp_path, monkeypatch)
    receipt = driver.run_origin_reload(args, guest=guest)
    assert receipt["success"] is True
    prepared = [event for event in events if event[0] == "prepare"]
    assert len(prepared) == 1 and prepared[0][2:] == (
        pathlib.Path(tmp_path / "seed/fetched-disk3.adf"), "F", "360")
    assert comparisons == [("reload-world", "F", "reload-F", True),
                           ("reload-items", "F", "reload-F", True)]
    keys = _keys(events)
    assert keys[keys.index("SPACE") + 1:keys.index("SPACE") + 3] == ["V", "E"]
    assert keys.count("I") == 1
    assert not FORBIDDEN_BEFORE_SAVE & set(keys)
    assert [event[1] for event in events if event[0] == "checkpoint"] == [
        "reload-world", "reload-items"]
    assert events[-1] == ("release", args.holder)
    stored = json.loads((args.out / "origin-reload-receipt.json").read_text())
    assert stored["checks"]["no_save_written"] is True
    assert stored["preservation_established"] is False


@pytest.mark.parametrize("fail, mismatch, changed_b", [
    (None, ("reload-world", "reload-F"), False),
    ("capture-reload-items", None, False),
    (None, ("reload-items", "reload-F"), False),
    (None, None, True),
    ("elsewhere", None, False),
])
def test_reload_phase_fails_closed_and_releases(tmp_path, monkeypatch, fail, mismatch, changed_b):
    args, guest, events, _ = _reload_coordinator(
        tmp_path, monkeypatch, fail=fail, mismatch=mismatch, changed_b=changed_b)
    with pytest.raises(RouteError):
        driver.run_origin_reload(args, guest=guest)
    receipt = json.loads((args.out / "origin-reload-receipt.json").read_text())
    assert receipt["success"] is False
    assert events[-1] == ("release", args.holder)
    assert not FORBIDDEN_BEFORE_SAVE & set(_keys(events))
    assert (receipt["checks"].get("no_save_written") is True) is (not changed_b)
    assert receipt["checks"].get("reloaded_square") is (fail != "elsewhere")
    if changed_b:
        assert any("reload7_save" in item for item in receipt["cleanup"])


def test_reload_phase_needs_a_fresh_run_before_preparing(tmp_path, monkeypatch):
    args, guest, events, _ = _reload_coordinator(tmp_path, monkeypatch)
    args.out.parent.mkdir(parents=True)
    with pytest.raises(RouteError, match="reload7_privacy"):
        driver.run_origin_reload(args, guest=guest)
    assert not [event for event in events if event[0] in ("prepare", "boot")]


def test_return_left_on_the_departure_square_still_saves_and_compares_but_fails(
        tmp_path, monkeypatch):
    args, guest, events, comparisons, _, _ = _return_coordinator(
        tmp_path, monkeypatch, fail="moved")
    with pytest.raises(RouteError, match="return_square"):
        driver.run_origin_return(args, guest=guest)
    receipt = json.loads((args.out / "origin-return-receipt.json").read_text())
    assert "error" not in receipt and receipt["success"] is False
    assert receipt["return_square_matches_start"] is True
    assert receipt["return_square_matches_arrival"] is False
    assert receipt["checks"]["return_square"] is False
    assert _keys(events).count("F") == 1
    assert comparisons[-1] == ("post-f", "F", "return-new-F", True)
    assert events[-1] == ("release", args.holder)


def test_return_action_deadline_leaves_the_cleanup_reserve(tmp_path, monkeypatch):
    args, guest, events, _, _, _ = _return_coordinator(tmp_path, monkeypatch)
    clock = {"now": 1000.0}
    monkeypatch.setattr(driver.time, "monotonic", lambda: clock["now"])
    real = driver._source_compare

    def compare(entry, *a, **kw):
        if entry["checkpoint"] == "pre-travel":
            # The action allowance is spent; 299 of the 300 reserved seconds remain.
            clock["now"] = 1000.0 + args.budget - 299
        return real(entry, *a, **kw)

    monkeypatch.setattr(driver, "_source_compare", compare)
    with pytest.raises(RouteError, match="return7_deadline"):
        driver.run_origin_return(args, guest=guest)
    assert ("trip", args.holder) not in events and "F" not in _keys(events)
    stops = [event for event in events if event[0] == "stop"]
    assert len(stops) == 1 and stops[0][2] == 30.0
    assert [event[1] for event in events if event[0] == "fetch"] == ["disk1", "disk2", "disk3"]
    assert events[-1] == ("release", args.holder)


@pytest.mark.parametrize("phase", ["return", "reload"])
def test_a_failed_halt_still_releases_the_lane(tmp_path, monkeypatch, phase):
    if phase == "return":
        args, guest, events, _, _, _ = _return_coordinator(tmp_path, monkeypatch)
        run = driver.run_origin_return
        name = "origin-return-receipt.json"
    else:
        args, guest, events, _ = _reload_coordinator(tmp_path, monkeypatch)
        run = driver.run_origin_reload
        name = "origin-reload-receipt.json"
    guest.stop_fails = True
    with pytest.raises(RouteError, match="injected stop failure"):
        run(args, guest=guest)
    receipt = json.loads((args.out / name).read_text())
    assert receipt["success"] is False
    assert any("stop: injected stop failure" in item for item in receipt["cleanup"])
    assert not [event for event in events if event[0] == "fetch"]
    assert events[-1] == ("release", args.holder)


@pytest.mark.parametrize("budget, ok", [(900, False), (901, True), (1500, True), (1501, False)])
def test_reload_budget_is_bounded_before_preparing(tmp_path, monkeypatch, budget, ok):
    args, guest, events, _ = _reload_coordinator(tmp_path, monkeypatch)
    args.budget = budget
    if ok:
        assert driver.run_origin_reload(args, guest=guest)["success"] is True
    else:
        with pytest.raises(RouteError, match="reload7_deadline"):
            driver.run_origin_reload(args, guest=guest)
        assert not events


def test_pinned_origin_return_square_is_the_foyer_area_82_init_writes():
    assert driver.ORIGIN_RETURN_SQUARE == (7, 15, 0)
    assert driver.ORIGIN_LIVE_AREA == 82


def _slow_title(tmp_path, monkeypatch, *, appears, states):
    """A GuardedRun whose title shows `appears` seconds after the wait begins, on a fake clock."""
    clock = {"now": 0.0}
    # A clock for this module alone, so pytest's own timing keeps the real one.
    monkeypatch.setattr(driver, "time", SimpleNamespace(
        monotonic=lambda: clock["now"], sleep=lambda seconds: None, time=lambda: 0.0))
    pressed = []
    guest = SimpleNamespace(press=lambda holder, key, timeout: pressed.append(key))
    guards = {state: object() for state in states}
    run = driver.GuardedRun(guest, "generated-holder", tmp_path / "screens", guards, 10_000.0)
    seen = []

    def see(state, limit=None):
        seen.append((state, limit))
        if state not in run.guards:
            raise RouteError(f"the required {state} screen has no existing guard")
        if state == "title":
            if clock["now"] + limit >= appears:
                clock["now"] = max(clock["now"], appears)
                return tmp_path / "title.png"
            clock["now"] += limit
            raise RouteError(f"title did not match its existing guard within {limit:.0f}s")
        return tmp_path / f"{state}.png"

    run.see = see
    return run, seen, pressed, clock


def test_a_late_title_is_awaited_when_the_guard_set_has_no_intro(tmp_path, monkeypatch):
    # The intro is still on screen after the first two waits; the title follows by itself.
    run, seen, pressed, clock = _slow_title(tmp_path, monkeypatch, appears=300,
                                            states=("title", "party_menu"))
    run.title()
    assert [state for state, _ in seen] == ["title", "title", "title"]
    assert pressed == [] and clock["now"] == 300


def test_a_title_that_never_comes_stops_at_the_title_limit_without_keys(tmp_path, monkeypatch):
    run, seen, pressed, clock = _slow_title(tmp_path, monkeypatch, appears=10_000,
                                            states=("title",))
    with pytest.raises(RouteError, match="within 420s"):
        run.title()
    assert {state for state, _ in seen} == {"title"} and pressed == []
    assert clock["now"] == driver.route_darkness.DARKNESS.title_limit


def test_a_guarded_intro_is_still_skipped_after_the_boot_span(tmp_path, monkeypatch):
    run, seen, pressed, _ = _slow_title(tmp_path, monkeypatch, appears=300,
                                        states=("title", "intro"))
    run.title()
    assert [state for state, _ in seen] == ["title", "title", "intro", "title"]
    assert pressed == ["ESC"]


class _FsuaeGuest(_Guest):
    """A recording FS-UAE lane: a debugger connection, a screen channel, and a live copy of F."""

    def __init__(self, events, remotes, running=True):
        super().__init__(events, remotes)
        self.gdb = object()
        self.shots = []
        self.running = running

    class _Emulator:
        def __init__(self, guest):
            self.guest = guest

        def poll(self):
            return None if self.guest.running else 0

    @property
    def emulator(self):
        return self._Emulator(self)

    def press(self, holder, key, timeout):
        self.events.append(("lane-key", key))

    def shot(self, path):
        self.shots.append(path)

    def get(self, remote, local, timeout):
        if self.running:
            raise RouteError("still open in a running emulator")
        return super().get(remote, local, timeout)

    def get_live(self, remote, local, timeout):
        self.events.append(("get_live", remote))
        local.write_bytes(b"Generated live F marker")
        return "fetched"


def _fsuae_wiring(monkeypatch, events):
    """Targets built on a guest's connection and legs run in this process, recorded."""
    built = []

    class Target:
        def __init__(self, debugger, layout):
            built.append(debugger)

        def locate(self, memory=None):
            events.append(("located",))

    monkeypatch.setattr(driver.amiga, "AmigaTarget", Target)
    monkeypatch.setattr(driver, "_measured_regions", lambda target, check_target: None)
    monkeypatch.setattr(driver, "_run_trip", lambda *a: pytest.fail("FS-UAE used the WinUAE subprocess"))
    monkeypatch.setattr(driver.fasttravelrun, "SETTLE_SECONDS", 0)
    return built


def test_fsuae_target_is_built_on_the_guests_debugger_connection(monkeypatch):
    events = []
    built = _fsuae_wiring(monkeypatch, events)
    monkeypatch.setattr(driver, "_target", lambda holder: pytest.fail("FS-UAE used the WinUAE pipe"))
    guest = _FsuaeGuest(events, {})
    driver._target_on("holder", driver.SourcePrivateGuest(guest, pathlib.Path()))
    assert built == [guest.gdb] and events == [("located",)]


def test_winuae_target_still_comes_from_the_pipe(monkeypatch):
    monkeypatch.setattr(driver, "_target", lambda holder: ("pipe", holder))
    assert driver._target_on("holder", _Guest([], {})) == ("pipe", "holder")


def test_fsuae_trip_runs_both_legs_in_process_on_the_guests_channels(tmp_path, monkeypatch):
    events = []
    built = _fsuae_wiring(monkeypatch, events)
    guest = _FsuaeGuest(events, {})
    seen = {}

    def run_legs(title, disks, to, back, arrival_answer, peek_vars, out, target, shot, press,
                 budget, *, report, **kw):
        seen.update(title=title, to=to, back=back, arrival=arrival_answer, target=target,
                    shot=shot, budget=budget)
        press("RET")
        report({"result": "idle", "settled": True})
        report({"result": "idle", "settled": True})

    monkeypatch.setattr(driver.fasttravelrun, "run_legs", run_legs)
    legs = driver._origin_trip(guest, "holder", tmp_path, tmp_path / "trip", 2000)
    assert len(legs) == 2 and (tmp_path / "trip").is_dir()
    assert (seen["title"], seen["to"], seen["back"], seen["arrival"]) == (
        driver.TITLE, 22, True, ("RET",))
    assert seen["shot"] == guest.shot and len(built) == 1
    assert ("lane-key", "RET") in events


def test_fsuae_phase_reads_f_while_running_through_the_live_copy(tmp_path, monkeypatch):
    _synthetic_private_files(monkeypatch, tmp_path)
    guest = _FsuaeGuest([], {"disk3": "remote-disk3"})
    root = tmp_path / "run"
    root.mkdir(mode=0o700)
    private = driver.SourcePrivateGuest(guest, root)
    private.get("remote-disk3", root / "f.adf", timeout=5)
    assert guest.events == [("get_live", "remote-disk3")]
    guest.running = False
    private.get("remote-disk3", root / "f2.adf", timeout=5)
    assert guest.events[-1] == ("fetch", "disk3")


def test_fsuae_origin_return_runs_in_process_and_never_the_pipe_or_subprocess(
        tmp_path, monkeypatch):
    args, _, events, _, _, disks = _return_coordinator(tmp_path, monkeypatch)
    guest = _FsuaeGuest(events, {key: f"remote-{key}" for key in disks}, running=False)
    built = _fsuae_wiring(monkeypatch, events)
    monkeypatch.setattr(driver, "_target", lambda holder: pytest.fail("FS-UAE used the WinUAE pipe"))

    def run_legs(title, disks_dir, to, back, arrival, peek, out, target, shot, press, budget, *,
                 report, **kw):
        events.append(("trip", args.holder))
        legs = [{"result": "idle", "settled": True, "areas_seen": [82, 22], "arrival_keys": ["RET"]},
                {"result": "idle", "settled": True, "areas_seen": [22, 82], "arrival_keys": ["RET"]}]
        _trip_log(out / "fasttravel.jsonl", legs)
        for leg in legs:
            report(leg)

    monkeypatch.setattr(driver.fasttravelrun, "run_legs", run_legs)
    args.emulator, args.audio_proof = "fsuae", None
    receipt = driver.run_origin_return(args, guest=guest)
    assert receipt["success"] is True and receipt["emulator"] == "fsuae"
    assert built and all(debugger is guest.gdb for debugger in built)
    assert ("trip", args.holder) in events


def test_fsuae_build_uses_the_darkness_pool_game_and_first_key_age():
    from tools.amiga import fsuaesession

    guest = driver._origin_guest(SimpleNamespace(emulator="fsuae"), None)
    assert isinstance(guest, fsuaesession.FsuaeGuest) and guest.game == "amiga-darkness"
    assert guest.first_key_after == fsuaesession.FIRST_KEY_AFTER["darkness"]


@pytest.mark.parametrize("phase", ["origin-return", "origin-reload"])
@pytest.mark.parametrize("extra, message", [
    (["--emulator", "fsuae", "--audio-proof", "a.json"], "belongs to --emulator winuae"),
    ([], "required with --emulator winuae"),
])
def test_audio_proof_belongs_to_winuae_only(phase, extra, message, capsys):
    command = [phase, "--run-id", "r", "--holder", "h", "--source-manifest", "s.json",
               "--controls", "c.json", "--out", "o", "--budget", "1000",
               *(["--return-receipt", "rr.json"] if phase == "origin-reload"
                 else ["--manifest", "m.json"]), *extra]
    with pytest.raises(SystemExit):
        driver.main(command)
    assert message in capsys.readouterr().err


def test_fsuae_trip_gives_each_leg_half_the_time_left_up_to_900_seconds(tmp_path, monkeypatch):
    events = []
    _fsuae_wiring(monkeypatch, events)
    budgets = []
    monkeypatch.setattr(driver.fasttravelrun, "run_legs",
                        lambda *a, report, **kw: budgets.append(a[10]))
    guest = _FsuaeGuest(events, {})
    driver._origin_trip(guest, "holder", tmp_path, tmp_path / "a", 2000)
    driver._origin_trip(guest, "holder", tmp_path, tmp_path / "b", 1000)
    assert budgets == [900.0, 500.0]


def test_fsuae_trip_turns_a_dropped_debugger_connection_into_a_route_error(tmp_path, monkeypatch):
    events = []
    _fsuae_wiring(monkeypatch, events)

    def dropped(*a, **kw):
        raise driver.amiga.FsuaeError("the connection closed")

    monkeypatch.setattr(driver.fasttravelrun, "run_legs", dropped)
    with pytest.raises(RouteError, match="the connection closed"):
        driver._origin_trip(_FsuaeGuest(events, {}), "holder", tmp_path, tmp_path / "t", 2000)


def test_fsuae_origin_reload_reads_through_the_guests_connection(tmp_path, monkeypatch):
    args, _, events, _ = _reload_coordinator(tmp_path, monkeypatch)
    guest = _FsuaeGuest(events, {key: f"remote-{key}" for key in ("disk1", "disk2", "disk3")},
                        running=False)
    root = args.out.parent
    guest.contents = {"disk3": lambda: (root / "disk3.adf").read_bytes()}
    built = _fsuae_wiring(monkeypatch, events)
    monkeypatch.setattr(driver, "_target", lambda holder: pytest.fail("FS-UAE used the WinUAE pipe"))
    args.emulator, args.audio_proof = "fsuae", None
    receipt = driver.run_origin_reload(args, guest=guest)
    assert receipt["success"] is True and receipt["emulator"] == "fsuae"
    assert built and all(debugger is guest.gdb for debugger in built)


class _NoShot(_FsuaeGuest):
    shot = None


class _NoLiveGet(_FsuaeGuest):
    get_live = None


@pytest.mark.parametrize("phase", ["return", "reload"])
@pytest.mark.parametrize("guest_class, missing", [(_NoShot, "shot"), (_NoLiveGet, "get_live")])
def test_fsuae_phase_stops_before_booting_when_the_guest_lacks_a_call(
        tmp_path, monkeypatch, phase, guest_class, missing):
    if phase == "return":
        args, _, events, _, _, disks = _return_coordinator(tmp_path, monkeypatch)
        run = driver.run_origin_return
    else:
        args, _, events, _ = _reload_coordinator(tmp_path, monkeypatch)
        disks = ("disk1", "disk2", "disk3")
        run = driver.run_origin_reload
    guest = guest_class(events, {key: f"remote-{key}" for key in disks})
    args.emulator, args.audio_proof = "fsuae", None
    with pytest.raises(RouteError, match=f"no {missing} method"):
        run(args, guest=guest)
    assert not [event for event in events if event[0] in ("boot", "trip")]
