"""The foundation module's Pool of Radiance description, driven with a fake guest and patched readings."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

from goldbox import amiga_savegame, areas, dos_codec, geo
from goldbox.amiga_adf import AmigaDisk
from tests import gamedata
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.fakes import WinuaeLaneNames
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_accept import MapGuard, _IdentityMap
from tests.amiga.test_amigaacceptance_title import (
    NAMES,
    TitleGuest,
    _adf,
    _files,
    _letters,
    _read_slot,
    _slot,
)
from tests.registry.test_specimens import _unlock
from tests.support import amigasavegame as synthetic_amiga
from tools.amiga import acceptance as foundation
from tools.amiga import (
    amigasaves,
    route_camp,
    route_curse,
    route_darkness,
    route_pool,
    staging,
    winuaesession,
)
from tools.amiga import route as amiga_route
from tools.registry import scratch, specimens

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


def _manifest(tmp_path, start=START, expected_after=LATER):
    slots = [("A", _slot(start)), ("B", _slot(LATER))]
    disks = {"disk1": _adf(tmp_path / "disk1.adf", "ONE"),
             "disk2": _adf(tmp_path / "disk2.adf", "TWO"),
             "save": _adf(tmp_path / "save.adf", "POOLSAVE", slots)}
    data = {"disks": disks, "registered": {"specimen": _adf(tmp_path / "specimen.adf", "REG")},
            "loaded_letter": "A", "state_a": start, "names_a": NAMES,
            "expected_after": expected_after}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(data))
    return path


def _run(tmp_path, clock, *, guest=None, start=START, expected_after=LATER, **kw):
    guest = guest or TitleGuest(clock, save_key="save")
    guest.place = dict(start)
    kw.setdefault("accept", True)
    if not kw["accept"]:
        kw.setdefault("guard", None)
    else:
        kw.setdefault("guard", MapGuard(states=STATES, on=FIRST_SCREEN))
        kw.setdefault("identity", _IdentityMap())
    result = foundation.run_recon(
        _manifest(tmp_path, start, expected_after), guest=guest, holder="wish679-test",
        audio_proof=_audio_proof(tmp_path), title=_title(), **kw)
    return guest, result


def _keys(guest):
    return [c[2] for c in guest.calls if c[0] == "press"]


@pytest.mark.parametrize("letter", ["A", "D"])
def test_published_routes_load_source_letter_and_write_c_then_f(letter):
    for factory in (route_curse.published_title,
                    foundation.route_silver_blades.published_title):
        title = factory(letter)
        assert title.issue == "677"
        assert title.mounted == ("df0", "df1")
        assert title.save_disk == "df0"
        assert title.control_letter == "C" and title.after_letter == "F"
        assert title.kept_letters == (() if letter == "A" else ("A",))
        assert [key for key, _, kind in title.route if kind == "write"] == ["C", "F"]
        assert (letter, "loaded_menu", "key") in title.route
        assert title.turn == ("about" if letter == "D" else None)
        assert sum(kind == "move" for _, _, kind in title.route) == 2


@pytest.mark.parametrize("letter", ["A", "D"])
def test_published_silver_visits_the_items_screen_only_when_the_sheet_has_the_button(letter):
    blades = foundation.route_silver_blades
    with_items = blades.published_title(letter)
    without = blades.published_title(letter, items_screen=False)
    visits = [step for step in with_items.route if step[1] == "items"]
    assert visits == [("I", "items", "key")]
    assert ("I", "items", "key") not in without.route
    assert all(state != "items" for _, state, _ in without.measure_route)
    assert any(state == "items" for _, state, _ in with_items.measure_route)
    # The writes and the walk are unchanged, and still follow the sheet's exit.
    assert [k for k, _, kind in without.route if kind == "write"] == ["C", "F"]
    assert sum(kind == "move" for _, _, kind in without.route) == 2
    assert without.route[3:5] == (("V", "sheet", "key"), ("E", "loaded_menu", "key"))
    assert len(without.route) == len(with_items.route) - 2


def _prepared_published(tmp_path, monkeypatch, name="ssb", members_items=0):
    """A published-disk-one run prepared from synthetic disks; the first member's item count is forced."""
    key, exe, ext, make = (
        (foundation.route_silver_blades.TITLE, "/Secret", "sav",
         synthetic_amiga.synthetic_silver_blades) if name == "ssb" else
        (route_curse.CURSE_KEY, "/Curse", "dat", synthetic_amiga.synthetic_curse))
    source = tmp_path / "party.D64"
    source.write_bytes(b"synthetic source")
    disk1 = tmp_path / "disk1.adf"
    one = synthetic_amiga.synthetic_disk_one(key)
    disk1.write_bytes(one.to_bytes())
    disk2 = tmp_path / "disk2.adf"
    disk2.write_bytes(AmigaDisk.blank("Disk2").to_bytes())
    published = tmp_path / "POOLSAVE.ADF"
    converted = AmigaDisk(one.to_bytes())
    converted.write_file(f"/SAVE/savgamA.{ext}",
                         make(("GUY DE VALOIS",)) if name == "ssb" else make(("CONVERTED",)))
    published.write_bytes(converted.to_bytes())
    source_sha, image_sha = staging.sha256(source), staging.sha256(published)
    monkeypatch.setitem(foundation.PUBLISHED_SOURCES, (name, "c64"), source_sha)
    monkeypatch.setitem(foundation.PUBLISHED_DISKS, name, (
        staging.sha256(disk1), staging.sha256(disk2), exe, "Disk1"))
    monkeypatch.setattr(foundation.scratch, "cache_dir",
                        lambda *parts: tmp_path.joinpath("cache", *map(str, parts)))
    if name == "ssb":
        real = foundation.route_silver_blades._slot_reading

        def reading(disk, letter):
            out = real(disk, letter)
            if "inventory" in out:
                out["inventory"]["members"][0]["count"] = members_items
            return out

        monkeypatch.setattr(foundation.route_silver_blades, "_slot_reading", reading)
    report = {
        "specimen": str(source), "specimen_sha256": source_sha,
        "amiga_disk1": str(disk1), "amiga_disk2": str(disk2),
        "c64_disks_dir": str(tmp_path),
        "save_as": {"source": str(source), "to": "amiga", "slot": "A",
                    "destination": str(published), "written": [str(published)],
                    "losses": [], "dropped": []},
        "written": [str(published)], "written_sha256": {"POOLSAVE.ADF": image_sha},
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    return foundation.prepare_published(name, "items", report_path)


def test_published_silver_with_items_keeps_the_items_screen(tmp_path, monkeypatch):
    path = _prepared_published(tmp_path, monkeypatch, members_items=1)
    manifest, title = foundation._published_manifest(path, "ssb")
    assert manifest["items_screen"] is True
    assert ("I", "items", "key") in title.route


def test_published_silver_without_items_records_and_skips_it(tmp_path, monkeypatch):
    path = _prepared_published(tmp_path, monkeypatch, members_items=0)
    manifest, title = foundation._published_manifest(path, "ssb")
    assert manifest["items_screen"] is False
    assert all(state != "items" for _, state, _ in title.route)


@pytest.mark.parametrize("items,recorded", [(1, False), (0, True)])
def test_published_silver_blocks_an_items_screen_the_slot_contradicts(
        tmp_path, monkeypatch, items, recorded):
    path = _prepared_published(tmp_path, monkeypatch, members_items=items)
    manifest = json.loads(path.read_text())
    manifest["items_screen"] = recorded
    path.write_text(json.dumps(manifest))
    with pytest.raises(winuaesession.RouteError, match="items_screen disagrees"):
        foundation._published_manifest(path, "ssb")


def test_published_silver_blocks_a_manifest_without_items_screen_for_an_itemless_slot(
        tmp_path, monkeypatch):
    path = _prepared_published(tmp_path, monkeypatch, members_items=0)
    manifest = json.loads(path.read_text())
    del manifest["items_screen"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(winuaesession.RouteError, match="items_screen disagrees"):
        foundation._published_manifest(path, "ssb")


@pytest.mark.parametrize("reading,cause", [
    ({"missing": True, "sha256": None}, "is missing"),
    ({"sha256": "0", "decode_error": "ValueError: bad"}, "does not decode: ValueError: bad"),
])
def test_published_silver_names_why_the_slot_cannot_be_read(
        tmp_path, monkeypatch, reading, cause):
    path = _prepared_published(tmp_path, monkeypatch, members_items=1)
    monkeypatch.setattr(foundation.route_silver_blades, "_slot_reading",
                        lambda _disk, _letter: reading)
    with pytest.raises(winuaesession.RouteError, match=f"published slot {cause}"):
        foundation._published_manifest(path, "ssb")


def test_published_curse_blocks_an_items_screen_record(tmp_path, monkeypatch):
    path = _prepared_published(tmp_path, monkeypatch, name="curse")
    manifest = json.loads(path.read_text())
    manifest["items_screen"] = True
    path.write_text(json.dumps(manifest))
    with pytest.raises(winuaesession.RouteError, match="only a Silver Blades"):
        foundation._published_manifest(path, "curse")


@pytest.mark.parametrize("name,key,exe,ext,make", [
    ("curse", route_curse.CURSE_KEY, "/Curse", "dat", synthetic_amiga.synthetic_curse),
    ("ssb", foundation.route_silver_blades.TITLE, "/Secret", "sav",
     synthetic_amiga.synthetic_silver_blades),
])
@pytest.mark.parametrize("port,letter", [("c64", "A"), ("dos", "D")])
def test_published_prepare_preserves_exact_reported_disk_one_and_rejects_tampering(
        tmp_path, monkeypatch, port, letter, name, key, exe, ext, make):
    source = tmp_path / ("party.D64" if port == "c64" else "SAVGAMD.DAT")
    source.write_bytes(b"synthetic source")
    disk1 = tmp_path / "disk1.adf"
    one = synthetic_amiga.synthetic_disk_one(key)
    disk1.write_bytes(one.to_bytes())
    disk2 = tmp_path / "disk2.adf"
    disk2.write_bytes(AmigaDisk.blank("Disk2").to_bytes())
    published = tmp_path / "POOLSAVE.ADF"
    converted = AmigaDisk(one.to_bytes())
    converted.write_file(f"/SAVE/savgam{letter}.{ext}",
                         make(("GUY DE VALOIS",)) if name == "ssb" else make(("CONVERTED",)))
    published.write_bytes(converted.to_bytes())
    source_sha = staging.sha256(source)
    image_sha = staging.sha256(published)
    monkeypatch.setitem(foundation.PUBLISHED_SOURCES, (name, port), source_sha)
    monkeypatch.setitem(foundation.PUBLISHED_DISKS, name, (
        staging.sha256(disk1), staging.sha256(disk2), exe, "Disk1"))
    monkeypatch.setattr(foundation.scratch, "cache_dir",
                        lambda *parts: tmp_path.joinpath("cache", *map(str, parts)))
    report = {
        "specimen": str(source), "specimen_sha256": source_sha,
        "amiga_disk1": str(disk1), "amiga_disk2": str(disk2),
        "c64_disks_dir": str(tmp_path) if port == "c64" else None,
        "save_as": {"source": str(source), "to": "amiga", "slot": letter,
                    "destination": str(published), "written": [str(published)],
                    "losses": [], "dropped": []},
        "written": [str(published)], "written_sha256": {"POOLSAVE.ADF": image_sha},
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    manifest_path = foundation.prepare_published(name, f"test-{port}", report_path)
    manifest, title = foundation._published_manifest(manifest_path, name)
    assert manifest["loaded_letter"] == letter
    if name == "ssb":
        # The synthetic Guy carries nothing, so the route skips the items screen.
        assert manifest["items_screen"] is False
        assert all(state != "items" for _, state, _ in title.route)
    else:
        assert "items_screen" not in manifest
    assert manifest["published_source"] == {"path": str(published), "sha256": image_sha}
    assert (letter, "loaded_menu", "key") in title.route
    assert pathlib.Path(manifest["disks"]["df0"]["path"]).read_bytes() == published.read_bytes()
    assert pathlib.Path(manifest["disks"]["df1"]["path"]).read_bytes() == disk2.read_bytes()
    assert pathlib.Path(manifest["registered"]["published"]["path"]).read_bytes() == published.read_bytes()

    published.rename(tmp_path / "evicted-original.adf")
    foundation._published_manifest(manifest_path, name)

    class ClaimReached(WinuaeLaneNames):
        calls = 0

        def claim(self, *_args, **_kwargs):
            self.calls += 1
            raise winuaesession.RouteError("claim boundary reached")

    guest = ClaimReached()
    monkeypatch.setattr(winuaesession, "_mute_proof", lambda _path: True)
    monkeypatch.setattr(specimens, "add",
                        lambda *_args, **_kw: pytest.fail("measure registered a specimen"))
    result = foundation.run_recon(
        manifest_path, guest=guest, holder="wish677-test",
        audio_proof=tmp_path / "mute.json", title=title, measure=True,
        published_disk_one=True, published_name=name)
    assert guest.calls == 1
    assert result["error"] == "RouteError: claim boundary reached"

    manifest["published_source"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(winuaesession.RouteError, match="Save As report differs"):
        foundation._published_manifest(manifest_path, name)
    manifest["published_source"]["sha256"] = image_sha
    manifest_path.write_text(json.dumps(manifest))

    report["save_as"]["slot"] = "D" if letter == "A" else "A"
    report_path.write_text(json.dumps(report))
    with pytest.raises(winuaesession.RouteError, match="wrong source slot"):
        foundation.prepare_published(name, f"bad-{port}", report_path)

    manifest["disks"]["df0"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(winuaesession.RouteError, match="exact published image"):
        foundation._published_manifest(manifest_path, name)

    class Unclaimed(WinuaeLaneNames):
        def claim(self, *_args, **_kwargs):
            raise AssertionError("the guest was claimed before disk verification")

    with pytest.raises(winuaesession.RouteError, match="exact published image"):
        foundation.run_recon(
            manifest_path, guest=Unclaimed(), holder="wish677-test",
            audio_proof=tmp_path / "mute.json", title=title, measure=True,
            published_disk_one=True, published_name=name)

    manifest["disks"]["df0"]["sha256"] = image_sha
    manifest_path.write_text(json.dumps(manifest))
    cache_image = pathlib.Path(manifest["registered"]["published"]["path"])
    cache_image.chmod(0o600)
    cache_image.write_bytes(b"changed cached image")
    with pytest.raises(winuaesession.RouteError, match="published is missing or changed"):
        foundation._published_manifest(manifest_path, name)


@pytest.mark.parametrize("clock_a,clock_f,success", [
    ("04:20", "04:21", True),
    ("04:20", "04:19", False),
    ("23:59", "00:01", True),
])
@pytest.mark.parametrize("registry_problem", ["none", "add", "check", "release"])
def test_published_silver_uses_journal_preflight_and_answerer_with_working_df0(
        tmp_path, monkeypatch, clock, clock_a, clock_f, success, registry_problem):
    def read_slot(disk, letter):
        return {**_read_slot(disk, letter),
                "clock": clock_f if letter == "F" else clock_a}

    title = dataclasses.replace(
        foundation.route_silver_blades.published_title("A"),
        read_slot=read_slot, slot_letters=_letters, slot_files=_files)
    slots = [("A", _slot(START))]
    disks = {"df0": _adf(tmp_path / "df0.adf", "ONE", slots),
             "df1": _adf(tmp_path / "df1.adf", "TWO")}
    registered = {
        "source": _adf(tmp_path / "source.adf", "SOURCE"),
        "report": _adf(tmp_path / "report.adf", "REPORT"),
        "published": _adf(tmp_path / "published.adf", "ONE", slots),
        "disk_one": _adf(tmp_path / "disk-one.adf", "ONE", slots),
        "disk_two": _adf(tmp_path / "disk-two.adf", "TWO"),
    }
    (tmp_path / "published.adf").write_bytes((tmp_path / "df0.adf").read_bytes())
    registered["published"]["sha256"] = disks["df0"]["sha256"]
    (tmp_path / "disk-two.adf").write_bytes((tmp_path / "df1.adf").read_bytes())
    registered["disk_two"]["sha256"] = disks["df1"]["sha256"]
    manifest = {"mode": "published_disk_one", "issue": "677", "title": "ssb",
                "source_port": "c64", "loaded_letter": "A", "state_a": START,
                "names_a": NAMES, "clock_a": clock_a, "disks": disks,
                "registered": registered, "expected_after": None}
    manifest_path = tmp_path / "prepare.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(foundation, "_published_manifest", lambda *_: (manifest, title))

    class SilverGuest(TitleGuest):
        def put(self, local, remote, timeout=None):
            self.uploads[remote] = pathlib.Path(local).read_bytes()
            return super().put(local, remote, timeout=timeout)

        def press(self, holder, key, timeout=None):
            super().press(holder, key, timeout=timeout)
            if key == "F":
                self._write("F", self.place)

        def release(self, *args, **kwargs):
            receipt = super().release(*args, **kwargs)
            if registry_problem == "release":
                raise OSError("lane release blocked")
            return receipt

    guest = SilverGuest(clock, save_key="df0")
    guest.uploads = {}
    guest.place = dict(START)
    seen = []

    def add_specimen(*args, **kwargs):
        encoded = base64.b32encode(tmp_path.name.encode()).decode().rstrip("=").lower()
        assert args[:2] == ("amiga", f"wish-677-ssb-{encoded}-ojswg33oge")
        assert guest.calls[-1][0] == "get"
        assert not any(call[0] == "release" for call in guest.calls)
        seen.append("add")
        if registry_problem == "add":
            raise OSError("specimen tree is unavailable")
        specimen = tmp_path / "specimens" / "fetched-df0.adf"
        specimen.parent.mkdir()
        specimen.write_bytes(args[2][0].read_bytes())
        return specimen.parent

    def check_specimens(*_args, **_kwargs):
        seen.append("check")
        return ["recorded hash differs"] if registry_problem == "check" else []

    monkeypatch.setattr(foundation.specimens, "add", add_specimen)
    monkeypatch.setattr(foundation.specimens, "check_specimens", check_specimens)

    def preflight(_python):
        assert guest.calls == []
        seen.append("preflight")

    def answer(_holder, adf, _timeout):
        seen.append(("answer", adf))
        return 0, "answered"

    result = foundation.run_recon(
        manifest_path, guest=guest, holder="wish677-test",
        audio_proof=_audio_proof(tmp_path), title=title,
        guard=MapGuard(), identity=_IdentityMap(), accept=True,
        published_disk_one=True, published_name="ssb",
        journal_python="/usr/bin/python3", preflight=preflight, answer=answer,
        preserve_specimen=True)
    assert result["error"] == ""
    assert result["success"] is (success and registry_problem == "none"), result.get(
        "specimen_error")
    assert result["after_clock_advanced"] is success
    assert result["published_files_preserved"] is True
    assert seen == (["preflight", ("answer", tmp_path / "df0.adf"), "add",
                     *([] if registry_problem == "add" else ["check"])]
                    if success else ["preflight", ("answer", tmp_path / "df0.adf")])
    assert ("specimen" in result) is (success and registry_problem != "add")
    if success and registry_problem == "check":
        assert "recorded hash differs" in result["specimen_error"]
        assert "recorded hash differs" in json.loads(foundation._summary(
            result, manifest_path, "recon1"))["error"]
        assert pathlib.Path(result["specimen"]["path"]).is_file()
        assert result["specimen"]["sha256"] == staging.sha256(
            tmp_path / "recon1" / "fetched-df0.adf")
    if success and registry_problem == "add":
        assert "specimen tree is unavailable" in result["specimen_error"]
        assert "specimen tree is unavailable" in json.loads(foundation._summary(
            result, manifest_path, "recon1"))["error"]
    if success and registry_problem == "release":
        assert "lane release blocked" in result["release_error"]
        assert "lane release blocked" in json.loads(foundation._summary(
            result, manifest_path, "recon1"))["error"]
        assert "specimen" in result
    assert any(call[0] == "release" for call in guest.calls)
    assert (tmp_path / "recon1" / "fetched-df0.adf").is_file()
    assert "X" not in _keys(guest) and "RET" not in _keys(guest)
    assert [key for key in _keys(guest) if key in ("C", "F")] == ["C", "F"]
    assert guest.uploads[guest.starts[0][0][0]] == (tmp_path / "published.adf").read_bytes()
    assert guest.uploads[guest.starts[0][0][1]] == (tmp_path / "disk-two.adf").read_bytes()
    assert guest.remote[guest.starts[0][0][1]] == (tmp_path / "df1.adf").read_bytes()
    fetched = AmigaDisk.open(tmp_path / "recon1" / "fetched-df0.adf")
    assert _letters(fetched) == ["A", "C", "F"]
    assert fetched.read_file("/SAVE/savgamA.sav") == AmigaDisk.open(
        tmp_path / "published.adf").read_file("/SAVE/savgamA.sav")

    if clock_a == "04:20" and clock_f == "04:21" and registry_problem == "none":
        measured = TitleGuest(clock, save_key="df0")
        measured.place = dict(START)
        before = list(seen)
        measure_result = foundation.run_recon(
            manifest_path, guest=measured, holder="wish677-measure",
            audio_proof=_audio_proof(tmp_path), title=title, measure=True,
            published_disk_one=True, published_name="ssb", attempt="measure1")
        assert measure_result["success"] is True, measure_result.get("error")
        assert seen == before
        assert "specimen" not in measure_result
        assert not any(call[0] == "press" and call[2] in ("C", "F")
                       for call in measured.calls)


@pytest.fixture
def specimen_root(tmp_path, monkeypatch):
    root = tmp_path / "specimens"
    monkeypatch.setattr(specimens, "tree_root", lambda: root)
    yield root
    # The specimen tool leaves the tree read-only, which a simple rmtree cannot remove.
    if root.is_dir():
        _unlock(root)


def test_published_specimen_name_is_idempotent_and_blocks_changed_source(tmp_path, specimen_root):
    root = specimen_root
    run = tmp_path / "run"
    fetched = run / "accept1" / "fetched-df0.adf"
    fetched.parent.mkdir(parents=True)
    fetched.write_bytes(b"game-written DF0")
    manifest = run / "prepare.json"
    first = foundation._preserve_published(manifest, "accept1", "ssb", fetched)
    assert first == foundation._preserve_published(manifest, "accept1", "ssb", fetched)
    assert specimens.check_specimens(root) == []
    assert first["sha256"] == staging.sha256(fetched)
    assert pathlib.Path(first["path"]).read_bytes() == fetched.read_bytes()
    assert pathlib.Path(first["provenance"]).is_file()
    fetched.write_bytes(b"another run at same name")
    with pytest.raises(winuaesession.RouteError, match="specimen name collision"):
        foundation._preserve_published(manifest, "accept1", "ssb", fetched)
    assert pathlib.Path(first["path"]).read_bytes() == b"game-written DF0"


def test_published_specimen_dotted_run_ids_have_distinct_valid_names(tmp_path, specimen_root):
    root = specimen_root
    outputs = []
    for run_id in ("ssb.c64", "ssb-c64"):
        manifest = tmp_path / run_id / "prepare.json"
        fetched = manifest.parent / "accept.1" / "fetched-df0.adf"
        fetched.parent.mkdir(parents=True)
        fetched.write_bytes(run_id.encode())
        saved = foundation._preserve_published(manifest, "accept.1", "ssb", fetched)
        outputs.append(saved)
        assert run_id in pathlib.Path(saved["provenance"]).read_text()
    assert outputs[0]["path"] != outputs[1]["path"]
    assert specimens.check_specimens(root) == []


def test_summary_keeps_route_error_ahead_of_preservation_error(tmp_path):
    summary = foundation._summary(
        {"success": False, "error": "RouteError: screen failed",
         "specimen_error": "OSError: registry failed", "unguarded": []},
        tmp_path / "prepare.json", "accept1")
    assert json.loads(summary)["error"] == "RouteError: screen failed"


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


def test_prepare_blocks_a_specimen_whose_sha256_differs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    other = tmp_path / "other.adf"
    other.write_bytes(b"not the specimen")
    with pytest.raises(winuaesession.RouteError, match="specimen SHA-256 differs"):
        foundation.prepare(foundation.POOL, "blocked", specimen=other)
    assert not (tmp_path / ".cache").exists()


def test_prepare_blocks_a_title_that_is_not_registered_here(tmp_path):
    with pytest.raises(winuaesession.RouteError, match="not one of this module's titles"):
        foundation.prepare(_title(), "x")


def test_prepare_blocks_a_run_id_that_is_not_lane_safe():
    with pytest.raises(winuaesession.RouteError, match="run id"):
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


def test_main_exits_two_when_the_run_is_blocked(tmp_path, capsys):
    assert foundation.main(["prepare", "--title", "pool", "--run-id", "a b"]) == 2
    assert "run id" in capsys.readouterr().err


# What needs the player's own disks and the specimen tree; CI has neither.
def _registered():
    try:
        specimen = specimens.tree_root().joinpath(*route_pool.POOL_SPECIMEN)
        if not specimen.is_file():
            pytest.skip("the Pool specimen is not in the registry")
        staging._find_images({"disk1": route_pool.POOL_DISK1_SHA256,
                                 "disk2": route_pool.POOL_DISK2_SHA256})
    except winuaesession.RouteError:
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
    try:
        route_pool._disk_geo("GEO00")
    except winuaesession.RouteError:
        pytest.skip("the C64 Pool disks that hold the wall data are not here")
    before = {label: hashlib.sha256(data).hexdigest()
              for label, data in amigasaves.images()}
    specimen_before = staging.sha256(specimen)
    monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    path = foundation.prepare(foundation.POOL, "registry-run")
    manifest = json.loads(path.read_text())
    assert manifest["title"] == "pool"
    assert manifest["state_a"] == START and manifest["expected_after"] == LATER
    assert manifest["loaded_letter"] == "A" and manifest["names_a"][0] == "BRUTUS"
    assert set(manifest["disks"]) == {"disk1", "disk2", "save"}
    for key, entry in manifest["disks"].items():
        assert staging.sha256(pathlib.Path(entry["path"])) == entry["sha256"]
        assert pathlib.Path(entry["path"]).is_relative_to(tmp_path)
    assert manifest["disks"]["disk1"]["sha256"] == route_pool.POOL_DISK1_SHA256
    assert manifest["disks"]["save"]["sha256"] == route_pool.POOL_SPECIMEN_SHA256
    after = {label: hashlib.sha256(data).hexdigest()
             for label, data in amigasaves.images()}
    assert after == before and staging.sha256(specimen) == specimen_before
    # The manifest is one the driver accepts, before any lane is claimed.
    assert foundation._title_inputs(manifest, foundation.POOL)[2] == "A"


# Curse of the Azure Bonds: the control save is D, the after save F, and the game's own exit key E
# is never a save letter.
TITLE_STATES = ("party_menu", "load_picker", "loaded_menu", "disk_wait", "world", "camp",
                "camp_picker")
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
    result = foundation.run_recon(
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


def test_an_after_letter_of_e_is_blocked_at_construction():
    with pytest.raises(winuaesession.RouteError, match="presses a save or kept slot letter"):
        dataclasses.replace(foundation.CURSE, after_letter="E")


def test_the_boot_spans_are_pinned():
    assert foundation.POOL.boot_span == 150.0
    assert foundation.CURSE.boot_span == 120.0


def test_prepare_blocks_a_curse_specimen_whose_sha256_differs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    other = tmp_path / "other.adf"
    other.write_bytes(b"not the specimen")
    with pytest.raises(winuaesession.RouteError, match="specimen SHA-256 differs"):
        foundation.prepare(foundation.CURSE, "blocked", specimen=other)
    assert not (tmp_path / ".cache").exists()


def _curse_registered():
    specimen = specimens.tree_root().joinpath(*route_curse.CURSE_SPECIMEN)
    if not specimen.is_file():
        pytest.skip("the Curse specimen is not in the registry")
    try:
        staging._find_images({"diskb": route_curse.CURSE_DISK_B_SHA256})
    except winuaesession.RouteError:
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
              for label, data in amigasaves.images()}
    specimen_before = staging.sha256(specimen)
    monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    manifest = json.loads(foundation.prepare(foundation.CURSE, "registry-run").read_text())
    assert manifest["title"] == "curse"
    assert manifest["state_a"] == CURSE_START and manifest["expected_after"] == CURSE_LATER
    assert manifest["loaded_letter"] == "B" and set(manifest["disks"]) == {"diskb", "save"}
    assert manifest["disks"]["diskb"]["sha256"] == route_curse.CURSE_DISK_B_SHA256
    assert manifest["disks"]["save"]["sha256"] == route_curse.CURSE_SPECIMEN_SHA256
    after = {label: hashlib.sha256(data).hexdigest()
             for label, data in amigasaves.images()}
    assert after == before and staging.sha256(specimen) == specimen_before
    assert foundation._title_inputs(manifest, foundation.CURSE)[2] == "B"


def test_curse_prepare_threads_a_substitute_slot_through_to_the_manifest(
        tmp_path, monkeypatch):
    """`prepare(..., substitute=...)` for a `_SUBSTITUTABLE` title reaches
    `staging._prepare_from` and its substitution shows up in the manifest."""
    from tests.amiga.test_amigastagingsubstitute import _curse_disk

    _curse_registered()
    monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    substitute = _curse_disk(tmp_path, "substitute.adf", {"Z": ("REPLACEMENT",)})
    manifest = json.loads(foundation.prepare(
        foundation.CURSE, "substitute-run", substitute=substitute,
        substitute_letter="Z").read_text())
    assert manifest["names_a"] == ["REPLACEMENT"]
    assert manifest["substitute"] == {
        "path": str(substitute), "sha256": staging.sha256(substitute), "letter": "Z"}


def test_prepare_blocks_a_substitute_on_a_title_that_is_not_substitutable(
        tmp_path, monkeypatch):
    """`substitute` is only wired through `_SUBSTITUTABLE`; every other title
    stops with an error before a run folder is ever created.
    Pools of Darkness takes one, so the measure-only route, which loads no save, stands in."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    run_root = scratch.cache_dir("acceptance", amiga_route.ISSUE)
    before = set(run_root.iterdir()) if run_root.exists() else set()
    with pytest.raises(winuaesession.RouteError, match="takes no substitute slot"):
        foundation.prepare(foundation.DARKNESS_UNSTARTED, "no-substitute-run",
                           substitute=tmp_path / "x.adf")
    after = set(run_root.iterdir()) if run_root.exists() else set()
    assert after == before


# Pools of Darkness: disk 3 goes into DF1 when the boot asks for it, then SPACE; F is the control save
# and G the after save (both offered by the game's save picker, which lists A to H), and E is the game's exit key though slot E is a kept slot.
DARK_START = {"area": 2, "x": 1, "y": 2, "facing": geo.EAST}
DARK_LATER = dict(DARK_START, x=2)
DARK_STATES = ("title", "journal", "journal_answer", "party_menu", "load_from", "load_picker", "disk2_prompt",
               "loaded_menu", "sheet", "save_picker", "world", "camp", "camp_save_picker", "exit_game")
MEASURE_STATES = tuple(s for s in DARK_STATES if s != "title")  # boot crops are not named "title"
DARK_FIRST_SCREEN = {}  # the title crop is recognised by its own name, and nothing precedes it
DARK_KEYS = ["P", "L", "P", "B", "SPACE", "V", "E", "S", "F", "B", "X", "RET", "NP8", "E", "S", "G", "N"]
DARK_ACCEPT_STATES = ("journal", "journal_answer", "world", "camp", "exit_game")


class DarkGuest(TitleGuest):
    """The game writes slot F at its `F` and slot G at its `G`, with the party where the keys took it."""

    def press(self, holder, key, timeout=None):
        super(TitleGuest, self).press(holder, key, timeout)
        if key == "NP8":
            dx, dy = geo.STEP[self.place["facing"]]
            self.place["x"] += dx
            self.place["y"] += dy
        elif key == "F":
            self._write("F", self.place)
        elif key == "G":
            self._write("G", self.land or self.place)


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


def _dark_unstarted_title():
    return dataclasses.replace(foundation.DARKNESS_UNSTARTED, read_slot=_read_slot,
                               slot_letters=_letters, slot_files=_files)


def _dark_run(tmp_path, clock, *, guest=None, guard=None, title=None, **kw):
    guest = guest or DarkGuest(clock, save_key="disk3")
    guest.place = dict(DARK_START)
    kw.setdefault("accept", True)
    if kw["accept"]:
        kw.setdefault("identity", _IdentityMap())
        guard = guard or MapGuard(states=DARK_STATES, on=DARK_FIRST_SCREEN)
    result = foundation.run_recon(
        _dark_manifest(tmp_path), guest=guest, guard=guard, holder="wish679-test",
        audio_proof=_audio_proof(tmp_path), title=title or _dark_title(), **kw)
    return guest, result


def test_darkness_accept_presses_the_plans_keys_with_disk_3_mounted_in_df1_and_never_y(
        tmp_path, clock):
    guest, result = _dark_run(tmp_path, clock)
    assert result["error"] == "" and result["success"] is True, result["read"]
    keys = _keys(guest)
    assert result["unguarded"] == []
    assert keys == DARK_KEYS and "Y" not in keys
    assert guest.inserted == [(0, "C:/Amiga/Disks/wish679-wish679-test-disk2.adf")]
    assert keys[0] == "P"
    (drives, options), = guest.starts
    assert [d and d.rsplit("-", 1)[1] for d in drives] == ["disk1.adf", "disk3.adf"]
    assert options == ()
    order = [c[2] if c[0] == "press" else "insert" for c in guest.calls
             if c[0] in ("press", "insert")]
    assert order[3:6] == ["B", "insert", "SPACE"] and order[6] == "V"
    # E leaves the sheet once and never twice in a row at the party menu.
    assert keys[keys.index("L"):keys.index("S")].count("E") == 1
    assert result["read"]["verdicts"][0] == "slot F: did not move"
    assert result["read"]["verdicts"][1].startswith("slot G: moved 1 square")


@pytest.mark.parametrize("land", [dict(DARK_START), dict(DARK_START, x=2, area=1),
                                  dict(DARK_START, x=3)])
def test_darkness_fails_when_g_stays_or_is_on_another_map_or_two_squares_on(
        tmp_path, clock, land):
    guest = DarkGuest(clock, save_key="disk3", land=land)
    _, result = _dark_run(tmp_path, clock, guest=guest)
    assert result["success"] is False and result["walk"]["d_ok"] is False
    # Darkness's manifest is pinned, not substituted, so the stall is never excused.
    assert result["passed_except_walk"] is False


def test_darkness_accept_order_puts_the_control_save_before_the_walk_and_the_after_save_after(
        tmp_path, clock):
    guest, result = _dark_run(tmp_path, clock)
    order = [c[2] if c[0] == "press" else "insert" for c in guest.calls
             if c[0] in ("press", "insert")]
    assert order == "P L P B insert SPACE V E S F B X RET NP8 E S G N".split()
    assert result["events"] and not any("answer" in e or "interstitial" in e
                                        for e in result["events"])


@pytest.mark.parametrize("state", DARK_ACCEPT_STATES)
def test_darkness_accept_will_not_start_when_the_guard_map_lacks_a_new_state(
        tmp_path, clock, state):
    guard = MapGuard(states=tuple(s for s in DARK_STATES if s != state), on=DARK_FIRST_SCREEN)
    with pytest.raises(winuaesession.RouteError, match="screen guard map lacks"):
        _dark_run(tmp_path, clock, guard=guard)


def test_darkness_accept_route_answers_the_journal_with_explicit_steps_and_asks_no_answerer():
    darkness = foundation.DARKNESS
    assert darkness.route[8:] == (
        ("F", "loaded_menu", "write"), ("B", "journal", "key"),
        ("X", "journal_answer", "key"), ("RET", "world", "key"), ("NP8", "world", "move"),
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"), ("G", "exit_game", "write"),
        ("N", "camp", "key"))
    assert {"journal", "journal_answer", "world", "camp", "exit_game"} <= darkness.strict
    assert darkness.min_waits["exit_game"] == 20.0
    assert [row[0] for row in darkness.interstitials] == ["yes_no", "continue", "encounter"]
    assert darkness.interstitials == (
        ("yes_no", ("keys", "N"), frozenset({"world"}), 1),
        ("continue", ("keys", "RET"), frozenset({"world"}), 3),
        ("encounter", ("keys", "F"), frozenset({"world"}), 1))
    assert not any(kind == "answer" for _, _, kind in darkness.route)


def test_darkness_measure_ends_at_the_camp_save_picker_and_writes_nothing(tmp_path, clock):
    guest, result = _dark_run(tmp_path, clock, guard=MapGuard(states=MEASURE_STATES),
                              accept=False, measure=True)
    assert _keys(guest) == "P L P B SPACE V E B X RET NP8 E S".split()
    assert [d for d, _ in guest.inserted] == [0] and result["success"] is True
    assert result["control_sha256"] is None
    order = [c[2] if c[0] == "press" else "insert" for c in guest.calls
             if c[0] in ("press", "insert")]
    assert order == "P L P B insert SPACE V E B X RET NP8 E S".split()
    assert not {"F", "G", "I", "J", "Y"} & set(_keys(guest))


def test_darkness_route_and_measure_route_are_pinned_and_write_only_f_and_g():
    darkness = foundation.DARKNESS
    head = (("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
            ("B", "disk2_prompt", "key"), route_darkness.DISK2_INSERT,
            ("V", "sheet", "key"), ("E", "loaded_menu", "key"))
    assert darkness.route == head + (
        ("S", "save_picker", "key"), ("F", "loaded_menu", "write"), ("B", "journal", "key"),
        ("X", "journal_answer", "key"), ("RET", "world", "key"),
        ("NP8", "world", "move"), ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("G", "exit_game", "write"), ("N", "camp", "key"))
    assert darkness.measure_route == head + (
        ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", "world", "key"),
        ("NP8", "world", "move"), ("E", "camp", "key"), ("S", "camp_save_picker", "key"))
    assert darkness.min_waits["journal"] == 45.0
    assert darkness.min_waits["journal_answer"] == 3.0
    assert (darkness.control_letter, darkness.after_letter) == ("F", "G")
    assert not {"F", "G"} & set(darkness.kept_letters)
    assert {step[0] for step in darkness.route if step[2] == "write"} == {"F", "G"}


@pytest.mark.parametrize("letter", ["A", "H", "I", "J"])
def test_darkness_blocks_a_write_step_that_is_not_the_control_or_after_letter(letter):
    route = tuple((letter, state, kind) if kind == "write" and key == "F" else (key, state, kind)
                  for key, state, kind in foundation.DARKNESS.route)
    with pytest.raises(winuaesession.RouteError):
        dataclasses.replace(foundation.DARKNESS, route=route)


def test_the_real_darkness_readers_show_f_g_and_h_free_on_disk_3():
    try:
        images = staging._find_images({"disk3": route_darkness.DARKNESS_DISK3_SHA256})
    except winuaesession.RouteError:
        pytest.skip("the registered Pools of Darkness disk 3 is not here")
    disk = AmigaDisk(images["disk3"][1])
    assert foundation.DARKNESS.slot_letters(disk) == list("ABCDE")
    for letter in "FGH":
        assert foundation.DARKNESS.read_slot(disk, letter) == {"missing": True, "sha256": None}


def test_darkness_names_where_e_is_the_exit_key_and_nowhere_else():
    darkness = foundation.DARKNESS
    assert darkness.plain_keys == (("E", "loaded_menu"), ("E", "camp"))
    assert darkness.kept_letters == ("A", "C", "D", "E")
    assert darkness.title_limit == 420.0 and darkness.boot_span == 225.0
    assert [s[0][0] for s in darkness.route if s[2] == "insert"] == [0]
    assert all(row[1][0] != "insert" or row[1][1] == 1 for row in darkness.interstitials)
    with pytest.raises(winuaesession.RouteError, match="presses a save or kept slot letter"):
        dataclasses.replace(darkness, plain_keys=(("E", "camp"),))


def test_prepare_blocks_a_darkness_disk_whose_sha256_differs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    other = tmp_path / "other.adf"
    other.write_bytes(b"not disk 3")
    with pytest.raises(winuaesession.RouteError, match="specimen SHA-256 differs"):
        foundation.prepare(foundation.DARKNESS, "blocked", specimen=other)
    assert not (tmp_path / ".cache").exists()


def _darkness_registered():
    try:
        return staging._find_images({"disk1": route_darkness.DARKNESS_DISK1_SHA256,
                                        "disk2": route_darkness.DARKNESS_DISK2_SHA256,
                                        "disk3": route_darkness.DARKNESS_DISK3_SHA256})
    except winuaesession.RouteError:
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
              for label, data in amigasaves.images()}
    monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    manifest = json.loads(foundation.prepare(foundation.DARKNESS, "registry-run").read_text())
    assert manifest["title"] == "darkness"
    assert manifest["state_a"] == DARK_START and manifest["loaded_letter"] == "B"
    assert "expected_after" not in manifest
    assert set(manifest["disks"]) == {"disk1", "disk2", "disk3"}
    assert manifest["disks"]["disk3"]["sha256"] == route_darkness.DARKNESS_DISK3_SHA256
    after = {label: hashlib.sha256(data).hexdigest()
             for label, data in amigasaves.images()}
    assert after == before
    assert foundation._title_inputs(manifest, foundation.DARKNESS)[2] == "B"


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
    guest, _ = _dark_run(tmp_path, clock, guard=_dark_guard("yes_no", ["12-world"], world=1))
    assert _keys(guest).count("N") == 1 and "Y" not in _keys(guest)
    other = tmp_path / "other"
    other.mkdir()
    guest, _ = _dark_run(other, clock, guard=_dark_guard("yes_no", ["01-party_menu"], party_menu=1))
    assert "N" not in _keys(guest) and "Y" not in _keys(guest)


def test_darkness_presses_return_at_a_continue_page_three_times_at_most_and_only_for_the_world(
        tmp_path, clock):
    guest, _ = _dark_run(tmp_path, clock, guard=_dark_guard("continue", ["12-world"], world=1))
    assert _keys(guest).count("RET") == 4  # the route's own, then three page turns
    other = tmp_path / "other"
    other.mkdir()
    guest, _ = _dark_run(other, clock, guard=_dark_guard("continue", ["01-party_menu"], party_menu=1))
    assert "RET" not in _keys(guest)


class _EncounterGuard(MapGuard):
    """Shows the encounter bar at each named crop until the run has answered it there.

    The `world` rule is closed on such a crop until then, as the game's bar is not the world
    bar; a crop named `...-again-N` is the same state as the one without the suffix.
    """

    def __init__(self, stems):
        self.fired: set[str] = set()
        self.pending = set(stems)

        def encounter(path):
            if path.stem in self.pending and path.stem not in self.fired:
                self.fired.add(path.stem)
                return True
            return False

        def world(path):
            return self.shown(path) == "world" and not (
                path.stem in self.pending and path.stem not in self.fired)

        super().__init__(states=(*DARK_STATES, "encounter"),
                         on={**DARK_FIRST_SCREEN, "encounter": encounter, "world": world})

    def shown(self, path):
        return super().shown(path.with_name(re.sub(r"-again-\d+", "", path.name)))


class _EncounterGuest(DarkGuest):
    """The encounter stops the party's first `NP8`, and the next `F` flees it instead of saving."""

    stopped = False
    fleeing = False

    def press(self, holder, key, timeout=None):
        if key == "NP8" and not self.stopped:
            self.stopped = self.fleeing = True
            return super(TitleGuest, self).press(holder, key, timeout)
        if key == "F" and self.fleeing:
            self.fleeing = False
            return super(TitleGuest, self).press(holder, key, timeout)
        return super().press(holder, key, timeout)


def test_darkness_flees_an_encounter_once_and_presses_the_move_again_to_end_one_square_on(
        tmp_path, clock):
    guest, result = _dark_run(tmp_path, clock, guest=_EncounterGuest(clock, save_key="disk3"),
                              guard=_EncounterGuard(["13-world"]))
    keys = _keys(guest)
    assert result["error"] == "" and result["success"] is True, result["read"]
    assert keys.count("F") == 2 and keys.count("NP8") == 2  # the route's own F, then FLEE
    assert keys[keys.index("NP8") - 1] == "RET" and keys[keys.index("NP8") + 1] == "F"
    assert result["moves_again"] == [{"step": 13, "after": "encounter", "attempt": 1}]
    assert result["read"]["verdicts"][1].startswith("slot G: moved 1 square")


def test_darkness_presses_no_flee_key_for_an_encounter_screen_outside_the_world_wait(
        tmp_path, clock):
    guest, result = _dark_run(tmp_path, clock, guard=_EncounterGuard([]))
    other = tmp_path / "other"
    other.mkdir()
    guest, _ = _dark_run(other, clock, guard=_EncounterGuard(["01-party_menu"]))
    assert _keys(guest).count("F") == 1 and "moves_again" not in result


def test_darkness_stops_at_the_move_again_cap_and_writes_no_slot_g(tmp_path, clock):
    stems = ["13-world", *(f"13-world-again-{i}" for i in range(1, foundation.MOVE_AGAIN_LIMIT + 1))]
    guest, result = _dark_run(tmp_path, clock, guest=_EncounterGuest(clock, save_key="disk3"),
                              guard=_EncounterGuard(stems))
    keys = _keys(guest)
    assert result["success"] is False
    assert result["error"].startswith("RouteError: step 13 (world)")
    assert keys.count("NP8") == foundation.MOVE_AGAIN_LIMIT + 1 and "G" not in keys
    assert len(result["moves_again"]) == foundation.MOVE_AGAIN_LIMIT


def test_a_run_records_the_interstitial_screens_its_guard_map_cannot_recognise(tmp_path, clock):
    _, result = _dark_run(tmp_path, clock)
    assert result["interstitials_without_guard"] == ["continue", "encounter", "yes_no"]
    events = [json.loads(line) for line in (tmp_path / "recon1" / "run.jsonl").read_text().splitlines()]
    logged = [e for e in events if e["event"] == "interstitials_without_guard"]
    assert [e["screens"] for e in logged] == [["continue", "encounter", "yes_no"]]
    other = tmp_path / "other"
    other.mkdir()
    _, result = _dark_run(other, clock, guard=_dark_guard("continue", ["12-world"], world=1))
    assert result["interstitials_without_guard"] == ["encounter", "yes_no"]


def test_the_unguarded_interstitials_come_back_sorted_whatever_order_the_title_lists_them(
        tmp_path, clock):
    # Listed in reverse, and eight of them: a set of this many strings comes back in the sorted
    # order only once in forty thousand hash seeds, so an unsorted list cannot pass by luck.
    names = [f"screen_{c}" for c in "hgfedcba"]
    title = _dark_title()
    title = dataclasses.replace(title, interstitials=(
        *title.interstitials, *((n, ("keys", "RET"), frozenset({"world"}), 1) for n in names)))
    guest = DarkGuest(clock, save_key="disk3")
    guest.place = dict(DARK_START)
    result = foundation.run_recon(
        _dark_manifest(tmp_path), guest=guest,
        guard=MapGuard(states=DARK_STATES, on=DARK_FIRST_SCREEN), holder="wish679-test",
        audio_proof=_audio_proof(tmp_path), title=title, accept=True, identity=_IdentityMap())
    assert result["interstitials_without_guard"] == sorted([*names, "continue", "encounter", "yes_no"])


def test_a_strict_timeout_names_the_interstitial_screens_with_no_guard(tmp_path, clock):
    guard = MapGuard(states=DARK_STATES, on={"world": _never})
    _, result = _dark_run(tmp_path, clock, guard=guard)
    assert result["success"] is False
    assert "continue" in result["error"] and "yes_no" in result["error"]
    other = tmp_path / "other"
    other.mkdir()
    both = MapGuard(states=(*DARK_STATES, "continue", "encounter", "yes_no"),
                    on={"world": _never})
    _, result = _dark_run(other, clock, guard=both)
    assert result["interstitials_without_guard"] == []
    assert "no rule" not in result["error"]


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
    ("darkness", "B", "10-journal", 45.0),   # BEGIN loads the journal question, so the wait is long
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


def test_darkness_mounts_disks_1_and_3_and_stages_disk_2_as_a_spare_for_the_df0_insert():
    darkness = foundation.DARKNESS
    assert darkness.mounted == ("disk1", "disk3") and darkness.spares == ("disk2",)
    assert darkness.options == ()
    assert set(darkness.disk_keys) == {"disk1", "disk2", "disk3"}
    assert darkness.disk_prompts == frozenset({"disk2_prompt"})
    assert "disk2_prompt" in darkness.strict and darkness.min_waits["disk2_prompt"] == 10.0


def test_darkness_inserts_disk_2_into_df0_at_the_prompt_after_the_slot_letter():
    insert = ((0, "disk2", "SPACE"), "loaded_menu", "insert")
    head = (("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
            ("B", "disk2_prompt", "key"), insert)
    tail = (("V", "sheet", "key"), ("E", "loaded_menu", "key"), ("S", "save_picker", "key"))
    assert foundation.DARKNESS.route[:8] == head + tail
    assert foundation.DARKNESS.measure_route[:5] == head


def test_darkness_has_no_disk_prompt_interstitial_and_pins_its_boot_span_as_a_guess():
    # With disk 3 mounted no prompt appeared. The 225 s span puts the first key near the title in
    # the one measured boot; that timing is a guess until a title guard recognises the screen.
    assert [row[0] for row in foundation.DARKNESS.interstitials] == [
        "yes_no", "continue", "encounter"]
    assert foundation.DARKNESS.boot_span == 225.0
    first_four = (("P", "party_menu", "key"), ("L", "load_from", "key"),
                  ("P", "load_picker", "key"), ("B", "disk2_prompt", "key"))
    assert foundation.DARKNESS.measure_route[:4] == first_four
    assert foundation.DARKNESS.route[:4] == first_four
    # The load-from prompt offers POOLS, SECRET and EXIT; only POOLS (P) is ever chosen.
    assert "load_from" in foundation.DARKNESS.strict
    assert foundation.DARKNESS.min_waits["load_from"] == 20.0


def test_curse_leaves_the_intro_with_one_escape_and_only_while_waiting_for_the_title(
        tmp_path, clock):
    states = (*CURSE_STATES, "intro")
    guard = MapGuard(states=states, on={"title": _never, "intro": _on("title")})
    guest, result = _curse_run(tmp_path, clock, guard=guard)
    assert _keys(guest) == ["ESC"] and "title screen was not recognized" in result["error"]
    other = tmp_path / "other"
    other.mkdir()
    guard = MapGuard(states=states, on={"title": lambda p: True, "load_picker": _never,
                                        "intro": _on("01-load_picker")})
    guest, _ = _curse_run(other, clock, guard=guard)
    assert "ESC" not in _keys(guest)


def test_curse_measure_with_a_title_guard_presses_the_boot_escapes_and_skips_them(
        tmp_path, clock):
    """#711: measure mode must act on the boot's interstitial table, as accept mode does,
    or a Curse boot on the published disk-one path never reaches its title guard."""
    guard = MapGuard(states=(*CURSE_STATES, "intro"), on={
        "intro": lambda p: p.read_bytes() == b"frame 0",
        "front_end": lambda p: p.read_bytes() == b"frame 1",
        "title": lambda p: p.read_bytes() == b"frame 2"})
    guest, result = _curse_run(tmp_path, clock, accept=False, measure=True, guard=guard)
    assert _keys(guest) == "ESC ESC L B V E S".split()
    assert result["success"] is True, result.get("error")
    assert {"skipped": "ESC", "step": 1} in result["events"]
    assert {"skipped": "ESC", "step": 2} in result["events"]


def test_pool_measure_with_a_title_guard_presses_the_wheel_return_and_skips_it(tmp_path, clock):
    """#711: Pool's measure route also starts with the key the boot wait already pressed."""
    guard = MapGuard(states=STATES, on={
        "wheel": lambda p: p.read_bytes() == b"frame 0",
        "title": lambda p: p.read_bytes() == b"frame 1"})
    guest, result = _run(tmp_path, clock, accept=False, measure=True, guard=guard)
    assert _keys(guest) == "RET RET L RET A V E NP2 NP8 E S".split()
    assert result["success"] is True, result.get("error")
    assert {"skipped": "RET", "step": 1} in result["events"]


def _sb_published_manifest(tmp_path):
    slots = [("A", _slot(START))]
    disks = {"df0": _adf(tmp_path / "df0.adf", "ONE", slots),
             "df1": _adf(tmp_path / "df1.adf", "TWO")}
    data = {"disks": disks, "registered": {}, "loaded_letter": "A",
            "state_a": START, "names_a": NAMES}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(data))
    return path


@pytest.mark.parametrize("landing, keys", [
    ("title", "ESC P L A V I E E S".split()),
    ("party_menu", "ESC L A V I E E S".split()),
])
def test_published_silver_blades_measure_presses_escape_once_at_credits(
        tmp_path, clock, landing, keys):
    """#711: the published Silver Blades measure boot already worked; this pins both outcomes
    of the credits ESC now that measure mode's boot wait presses it itself."""
    title = dataclasses.replace(
        foundation.route_silver_blades.published_title("A"),
        read_slot=_read_slot, slot_letters=_letters, slot_files=_files)
    guest = TitleGuest(clock, save_key="df0")
    guest.place = dict(START)
    guard = MapGuard(states=("title", "credits", "party_menu", "load_picker", "loaded_menu",
                              "sheet", "items", "save_picker"),
                     on={"credits": lambda p: p.read_bytes() == b"frame 0",
                         landing: lambda p: p.read_bytes() == b"frame 1"})
    result = foundation.run_recon(
        _sb_published_manifest(tmp_path), guest=guest, guard=guard, holder="wish677-test",
        audio_proof=_audio_proof(tmp_path), title=title, accept=False, measure=True)
    assert _keys(guest) == keys
    assert result["success"] is True, result.get("error")
    if landing == "party_menu":
        assert {"skipped": "P", "step": 1} in result["events"]


def test_darkness_measure_with_a_title_guard_is_unaffected(tmp_path, clock):
    """#711: no Darkness interstitial row waits for `title`, so the boot wait still only
    watches for it passively, and the route's own first key (`P`) is unaffected."""
    seen = {"n": 0}

    def title_rule(path):
        seen["n"] += 1
        return seen["n"] >= 3

    guard = MapGuard(states=DARK_STATES, on={"title": title_rule})
    guest, result = _dark_run(tmp_path, clock, guard=guard, accept=False, measure=True)
    assert _keys(guest)[0] == "P"
    first_key = next(i for i, e in enumerate(result["events"]) if "key" in e)
    assert not any("interstitial" in e for e in result["events"][:first_key])


class _Called:
    """A stand-in `run_recon` that records its keywords and reports a passing run."""

    def __init__(self):
        self.calls = []

    def __call__(self, manifest, **kw):
        self.calls.append(kw)
        return {"success": True, "error": "", "unguarded": [], "read": {"verdicts": []}}


def _measure_args(tmp_path, *extra):
    return ["measure", "--title", "pool", "--manifest", str(tmp_path / "prepare.json"),
            "--audio-proof", str(tmp_path / "mute.json"), "--attempt", "measure1", *extra]


def test_measure_passes_the_guard_file_it_is_given_and_none_without_one(tmp_path, monkeypatch):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda path: ("guards", str(path)))
    assert foundation.main(_measure_args(tmp_path)) == 0
    assert called.calls[-1]["guard"] is None and called.calls[-1]["measure"] is True
    assert foundation.main(_measure_args(tmp_path, "--guards", "g.json")) == 0
    assert called.calls[-1]["guard"] == ("guards", "g.json")


def test_measure_blocks_an_unreadable_guards_file_before_any_run_starts(tmp_path, monkeypatch,
                                                                         capsys):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    missing = tmp_path / "missing.json"
    assert foundation.main(_measure_args(tmp_path, "--guards", str(missing))) == 2
    assert called.calls == [] and "acceptance:" in capsys.readouterr().err
    unreadable = tmp_path / "bad.json"
    unreadable.write_text("not json")
    assert foundation.main(_measure_args(tmp_path, "--guards", str(unreadable))) == 2
    assert called.calls == []


def test_accept_still_passes_its_guard_and_identity_files(tmp_path, monkeypatch):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda path: ("guards", str(path)))
    args = _measure_args(tmp_path, "--guards", "g.json", "--identity", "i.json")
    args[0] = "accept"
    assert foundation.main(args) == 0
    assert called.calls[-1]["guard"] == ("guards", "g.json")
    assert called.calls[-1]["identity"] == ("guards", "i.json")


def test_darkness_prepare_copies_disk_2_as_a_working_copy_never_the_registered_image(
        tmp_path, monkeypatch):
    _darkness_registered()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    manifest = json.loads(foundation.prepare(foundation.DARKNESS, "disk2-run").read_text())
    entry = manifest["disks"]["disk2"]
    assert entry["sha256"] == route_darkness.DARKNESS_DISK2_SHA256
    assert pathlib.Path(entry["path"]).is_relative_to(tmp_path)
    assert manifest["sources"]["disk2"]["sha256"] == route_darkness.DARKNESS_DISK2_SHA256


def test_darkness_never_presses_the_continuation_key_when_the_df0_insert_fails(tmp_path, clock):
    class Blocked(DarkGuest):
        def insert(self, holder, drive_number, remote, timeout=None, sha256=None):
            self.calls.append(("insert", drive_number, remote))
            exc = RuntimeError("drive 0 blocked")
            exc.receipt = {"status": "blocked"}
            raise exc

    guest, result = _dark_run(tmp_path, clock, guest=Blocked(clock, save_key="disk3"))
    assert result["success"] is False and _keys(guest) == ["P", "L", "P", "B"]
    event = next(e for e in result["events"] if "insert" in e)
    assert event["drive"] == 0 and event["insert"] == "disk2"
    assert event["error"] == "drive 0 blocked" and event["receipt"] == {"status": "blocked"}


def test_darkness_insert_carries_the_disk_2_hash(tmp_path, clock):
    seen = []

    class Watching(DarkGuest):
        def insert(self, holder, drive_number, remote, timeout=None, sha256=None):
            seen.append((drive_number, remote.rsplit("-", 1)[1], sha256))
            return super().insert(holder, drive_number, remote, timeout, sha256)

    _dark_run(tmp_path, clock, guest=Watching(clock, save_key="disk3"))
    sha = hashlib.sha256((tmp_path / "disk2.adf").read_bytes()).hexdigest()
    assert seen == [(0, "disk2.adf", sha)]


@pytest.mark.parametrize("guard", [None, "lacking"])
def test_darkness_measure_blocks_a_df0_insert_without_a_guard_on_the_prompt(
        tmp_path, clock, guard):
    if guard:
        guard = MapGuard(states=tuple(s for s in MEASURE_STATES if s != "disk2_prompt"), on={})
    guest = DarkGuest(clock, save_key="disk3")
    with pytest.raises(winuaesession.RouteError, match="disk2_prompt.*DF0 insert needs a guard"):
        _dark_run(tmp_path, clock, guest=guest, guard=guard, accept=False, measure=True)
    assert guest.calls == []


def test_darkness_measure_starts_when_the_guard_map_has_the_prompt(tmp_path, clock):
    guard = MapGuard(states=MEASURE_STATES)
    guest, result = _dark_run(tmp_path, clock, guard=guard, accept=False, measure=True)
    assert guest.starts and [d for d, _ in guest.inserted] == [0]


# The reload title: load the game-written slot G, write nothing, and judge the place on the screen.
RELOAD_KEYS = "P L P G SPACE V E B X RET".split()
G_PLACE = DARK_LATER
F_PLACE = DARK_START
G_KEY, F_KEY = foundation.place_state(G_PLACE), foundation.place_state(F_PLACE)
RELOAD_STATES = (*DARK_STATES, G_KEY, F_KEY)
G_LINE = f"slot G: reloaded at area 2 2,2 facing {G_PLACE['facing']}"
F_LINE = f"slot F: area 2 1,2 facing {F_PLACE['facing']} is not on the screen"


class ReloadGuest(TitleGuest):
    """The game shows `loads` after G is pressed at the load picker and writes only what `spoil` does."""

    def __init__(self, clock, *, loads=G_PLACE, spoil=None):
        super().__init__(clock, save_key="disk3", spoil=spoil)
        self.loads = loads

    def press(self, holder, key, timeout=None):
        super(TitleGuest, self).press(holder, key, timeout)
        if key == "G":
            self.place = dict(self.loads)
        elif key == "RET" and self.spoil:
            self.spoil(self)

    def write_file(self, path, raw):
        remote = next(r for r in self.mounted if r and r.endswith("-disk3.adf"))
        disk = AmigaDisk(self.remote[remote])
        disk.write_file(path, raw)
        self.remote[remote] = disk.to_bytes()


def _reload_title():
    return dataclasses.replace(foundation.DARKNESS_RELOAD, read_slot=_read_slot,
                               slot_letters=_letters, slot_files=_files)


def _reload_manifest(tmp_path):
    slots = [(letter, _slot(F_PLACE if letter != "G" else G_PLACE)) for letter in "ABCDEFG"]
    disks = {"disk1": _adf(tmp_path / "disk1.adf", "POD 1"),
             "disk2": _adf(tmp_path / "disk2.adf", "POD 2"),
             "disk3": _adf(tmp_path / "disk3.adf", "POD 3", slots)}
    data = {"disks": disks,
            "registered": {"accept_disk3": _adf(tmp_path / "accept3.adf", "POD 3", slots)},
            "loaded_letter": "G", "state_a": G_PLACE, "names_a": NAMES,
            "other_letter": "F", "other_place": F_PLACE}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(data))
    return path


def _reload_guard(guest, *, g=None, f=None, states=RELOAD_STATES):
    """Each place key checks the fake's current place, unless `g` or `f` replaces its rule."""
    on = {G_KEY: g or (lambda _p: guest.place == G_PLACE),
          F_KEY: f or (lambda _p: guest.place == F_PLACE)}
    return MapGuard(states=states, on=on)


def _reload_run(tmp_path, clock, *, guest=None, guard=None, title=None, **kw):
    guest = guest or ReloadGuest(clock)
    kw.setdefault("reload", True)
    kw.setdefault("identity", _IdentityMap())
    result = foundation.run_recon(
        _reload_manifest(tmp_path), guest=guest, guard=guard or _reload_guard(guest),
        holder="wish679-test", audio_proof=_audio_proof(tmp_path),
        title=title or _reload_title(), **kw)
    return guest, result


def test_reload_presses_the_route_writes_nothing_and_judges_the_place_on_the_screen(
        tmp_path, clock):
    guest, result = _reload_run(tmp_path, clock)
    assert result["error"] == "" and result["success"] is True, result["read"]
    keys = _keys(guest)
    assert keys == RELOAD_KEYS
    assert not {"S", "F", "H", "N", "Y"} & set(keys)
    assert guest.inserted == [(0, "C:/Amiga/Disks/wish679-wish679-test-disk2.adf")]
    assert all(result["disks_unchanged"].values()) and len(result["disks_unchanged"]) == 3
    assert result["read"]["verdicts"] == [G_LINE, F_LINE]
    assert result["reload"]["shown"] is True and result["reload"]["other_shown"] is False
    assert all(result["kept_unchanged"].values()) and result["extra_saves"] == []
    assert result["read"]["loaded_letter"] == "G"


def test_reload_fails_when_the_screen_shows_the_other_slots_place(tmp_path, clock):
    guest = ReloadGuest(clock, loads=F_PLACE)
    _, result = _reload_run(tmp_path, clock, guest=guest)
    assert result["success"] is False
    assert result["reload"]["shown"] is False
    assert result["read"]["verdicts"][0] == (
        f"slot G: area 2 2,2 facing {G_PLACE['facing']} is not on the screen")


def test_reload_fails_when_the_place_guard_matches_both_places(tmp_path, clock):
    guest = ReloadGuest(clock)
    guard = _reload_guard(guest, f=lambda _p: True, g=lambda _p: True)
    _, result = _reload_run(tmp_path, clock, guest=guest, guard=guard)
    assert result["completed"] is True and result["reload"]["shown"] is True
    assert result["reload"]["other_shown"] is True and result["success"] is False
    assert result["read"]["verdicts"] == [
        G_LINE, f"slot F: area 2 1,2 facing {F_PLACE['facing']} is also on the screen"]


def test_reload_fails_when_the_place_guard_never_matches(tmp_path, clock):
    guest = ReloadGuest(clock)
    _, result = _reload_run(tmp_path, clock, guest=guest,
                            guard=_reload_guard(guest, g=lambda _p: False))
    assert result["success"] is False and "place screen was not recognized" in result[
        "error"].replace("place_x2_y2_f1", "place")
    assert result["reload"]["shown"] is False
    assert result["read"]["verdicts"][0].endswith("is not on the screen")


@pytest.mark.parametrize("spoil", [
    lambda guest: guest.write_file("/SAVE/savgamH.sav", _slot(G_PLACE)),
    lambda guest: guest.write_file("/SAVE/notes.dat", b"written by the game"),
], ids=["a slot H", "a file that is no slot"])
def test_reload_fails_when_the_game_writes_to_disk_3(tmp_path, clock, spoil):
    guest = ReloadGuest(clock, spoil=spoil)
    _, result = _reload_run(tmp_path, clock, guest=guest)
    assert result["completed"] is True and result["reload"]["shown"] is True
    assert result["disks_unchanged"]["disk3"] is False
    assert result["success"] is False


def test_reload_blocks_before_the_claim_when_a_guard_or_identity_rule_is_missing(
        tmp_path, clock):
    for missing in (G_KEY, F_KEY):
        guest = ReloadGuest(clock)
        states = tuple(s for s in RELOAD_STATES if s != missing)
        with pytest.raises(winuaesession.RouteError, match="screen guard map lacks"):
            _reload_run(tmp_path, clock, guest=guest, guard=_reload_guard(guest, states=states))
        assert guest.calls == []

    class SheetOnly:
        def __contains__(self, state):
            return state == "sheet"

        def __call__(self, state, path):
            return True

    for identity in (None, SheetOnly()):
        guest = ReloadGuest(clock)
        with pytest.raises(winuaesession.RouteError, match="identity map lacks"):
            _reload_run(tmp_path, clock, guest=guest, identity=identity)
        assert guest.calls == []


@pytest.mark.parametrize("title,mode", [
    ("reload", {"accept": True}), ("reload", {"measure": True}),
    ("darkness", {"reload": True}),
])
def test_a_title_with_no_save_letters_runs_only_as_a_reload(tmp_path, clock, title, mode):
    guest = ReloadGuest(clock)
    chosen = _reload_title() if title == "reload" else _dark_title()
    with pytest.raises(winuaesession.RouteError, match="reload"):
        _reload_run(tmp_path, clock, guest=guest, title=chosen, **{"reload": False, **mode})
    assert guest.calls == []


def test_the_reload_description_is_pinned():
    reload = foundation.DARKNESS_RELOAD
    assert foundation.TITLES["darkness-reload"] is reload
    assert route_darkness.DARKNESS_RELOAD_LOADED == "G"
    assert reload.route == reload.measure_route == (
        ("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
        ("G", "disk2_prompt", "key"), route_darkness.DISK2_INSERT,
        ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
        ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", "world", "key"))
    assert reload.route[3][0] == route_darkness.DARKNESS_RELOAD_LOADED
    assert reload.control_letter is None and reload.after_letter is None
    assert reload.kept_letters == ("A", "B", "C", "D", "E", "F")
    assert reload.plain_keys == (("E", "loaded_menu"), ("B", "journal"))
    assert reload.strict == {step[1] for step in reload.route}
    assert not any(kind in ("write", "move") for _, _, kind in reload.route)
    assert foundation.place_state(dict(area=2, x=2, y=2, facing=geo.EAST)) == "place_x2_y2_f1"
    assert foundation.DARKNESS.control_letter == "F"


def test_the_unstarted_darkness_description_is_pinned():
    unstarted = foundation.DARKNESS_UNSTARTED
    assert foundation.TITLES["darkness-unstarted"] is unstarted
    assert route_darkness.DARKNESS_UNSTARTED_LOADED == "A"
    route = (
        ("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
        ("A", "loaded_menu", "key"),
        ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
        ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", "yes_no", "key"),
        ("N", "continue", "key"), ("RET", "continue", "key"), ("RET", "world", "key"))
    assert unstarted.route == unstarted.measure_route == route
    assert unstarted.kept_letters == ("B", "C", "D", "E")
    assert unstarted.control_letter == "F" and unstarted.after_letter == "G"
    assert unstarted.plain_keys == (("E", "loaded_menu"), ("B", "journal"))
    assert unstarted.min_waits == {**foundation.DARKNESS.min_waits, "yes_no": 45.0,
                                   "continue": 10.0}
    # Slot A's load shows no disk 2 prompt, so the route has no step for it; the game may ask
    # later, and the optional row answers it wherever it does.
    assert unstarted.interstitials == (
        ("disk2_prompt", ("insert", 0, "disk2", "SPACE"),
         frozenset({"loaded_menu", "sheet", "journal", "journal_answer", "yes_no", "continue",
                    "world"}), 1),
        *foundation.DARKNESS.interstitials)
    assert not any(kind in ("write", "move") for _, _, kind in unstarted.route)
    assert foundation.DARKNESS.route[3][0] == "B"


UNSTARTED_KEYS = ["P", "L", "P", "A", "V", "E", "B", "X", "RET", "N", "RET", "RET"]
UNSTARTED_STATES = tuple(s for s in MEASURE_STATES if s != "sheet")


def _unstarted_run(tmp_path, clock, guest, on=None, states=UNSTARTED_STATES):
    return _dark_run(tmp_path, clock, guest=guest, title=_dark_unstarted_title(),
                     guard=MapGuard(states=states, on=on or {}), accept=False, measure=True)


def test_the_unstarted_darkness_route_needs_no_disk_2_prompt(tmp_path, clock):
    guest = DarkGuest(clock, save_key="disk3")
    guest, result = _unstarted_run(tmp_path, clock, guest)
    assert result["error"] == "" and result["success"] is True
    assert _keys(guest) == UNSTARTED_KEYS and guest.inserted == []


def test_the_unstarted_darkness_route_answers_a_disk_2_prompt_met_while_waiting_for_the_journal(
        tmp_path, clock):
    guest = DarkGuest(clock, save_key="disk3")
    on = {"disk2_prompt": lambda p: p.stem.endswith("-journal") and not guest.inserted,
          "journal": lambda p: p.stem.endswith("-journal") and bool(guest.inserted)}
    guest, result = _unstarted_run(tmp_path, clock, guest, on)
    assert result["error"] == "" and result["success"] is True
    order = [c[2] if c[0] == "press" else "insert" for c in guest.calls
             if c[0] in ("press", "insert")]
    assert order[6:10] == ["B", "insert", "SPACE", "X"]
    assert guest.inserted == [(0, "C:/Amiga/Disks/wish679-wish679-test-disk2.adf")]
    assert {"interstitial": "disk2_prompt", "key": "SPACE"} in result["events"]


def test_the_unstarted_darkness_route_answers_a_disk_2_prompt_met_at_the_unguarded_yes_no(
        tmp_path, clock):
    guest = DarkGuest(clock, save_key="disk3")
    on = {"disk2_prompt": lambda p: p.stem == "09-yes_no" and not guest.inserted}
    guest, result = _unstarted_run(tmp_path, clock, guest, on)
    assert result["error"] == "" and result["success"] is True
    order = [c[2] if c[0] == "press" else "insert" for c in guest.calls
             if c[0] in ("press", "insert")]
    assert order[8:12] == ["RET", "insert", "SPACE", "N"]
    assert {"interstitial": "disk2_prompt", "key": "SPACE"} in result["events"]
    assert any(e.get("state") == "09-yes_no-after-1" for e in result["events"])


def test_the_unstarted_darkness_route_inserts_disk_2_once_however_often_the_prompt_shows(
        tmp_path, clock):
    guest = DarkGuest(clock, save_key="disk3")
    shown = ("-journal", "-yes_no")
    on = {"disk2_prompt": lambda p: p.stem.endswith(shown),
          "journal": lambda p: p.stem.endswith("-journal") and bool(guest.inserted)}
    guest, result = _unstarted_run(tmp_path, clock, guest, on)
    assert result["error"] == "" and result["success"] is True
    assert len(guest.inserted) == 1


def test_a_disk_2_prompt_outside_the_rows_waiting_for_states_is_not_answered(tmp_path, clock):
    guest = DarkGuest(clock, save_key="disk3")
    states = tuple(s for s in UNSTARTED_STATES if s != "party_menu")
    on = {"disk2_prompt": lambda p: p.stem == "01-party_menu"}
    guest, result = _unstarted_run(tmp_path, clock, guest, on, states=states)
    assert guest.inserted == []


def test_a_measure_run_presses_no_key_for_an_interstitial_at_an_unguarded_state(tmp_path, clock):
    guest = DarkGuest(clock, save_key="disk3")
    states = (*(s for s in UNSTARTED_STATES if s != "world"), "continue")
    on = {"continue": lambda p: p.stem.endswith(("-continue", "12-world"))}
    guest, result = _unstarted_run(tmp_path, clock, guest, on, states=states)
    assert _keys(guest) == UNSTARTED_KEYS
    assert not any(e.get("interstitial") == "continue" for e in result["events"])


def test_the_unstarted_darkness_measure_blocks_a_guard_map_with_no_disk_2_prompt(tmp_path, clock):
    guest = DarkGuest(clock, save_key="disk3")
    states = tuple(s for s in UNSTARTED_STATES if s != "disk2_prompt")
    with pytest.raises(winuaesession.RouteError, match="disk2_prompt.*DF0 insert needs a guard on the prompt$"):
        _unstarted_run(tmp_path, clock, guest, states=states)
    assert guest.calls == []


@pytest.mark.parametrize("command", ["accept", "reload"])
def test_darkness_unstarted_only_measures(tmp_path, monkeypatch, capsys, command):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda path: ("guards", str(path)))
    args = _measure_args(tmp_path, "--guards", "g.json", "--identity", "i.json")
    args[0] = command
    args[args.index("--title") + 1] = "darkness-unstarted"
    assert foundation.main(args) == 2
    assert called.calls == [] and "only measures" in capsys.readouterr().err


def test_darkness_unstarted_prepare_loads_slot_a_and_leaves_the_registered_images_unchanged(
        tmp_path, monkeypatch):
    _darkness_registered()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    manifest = json.loads(foundation.prepare(
        foundation.TITLES["darkness-unstarted"], "unstarted-run").read_text())
    assert manifest["title"] == "darkness" and manifest["loaded_letter"] == "A"
    assert manifest["state_a"] == {"area": 0, "x": 7, "y": 13, "facing": 0}
    assert manifest["disks"]["disk3"]["sha256"] == route_darkness.DARKNESS_DISK3_SHA256
    assert foundation._title_inputs(manifest, foundation.TITLES["darkness-unstarted"])[2] == "A"


# Preparing a reload from a game-written disk 3, on synthetic disks.
def _reload_registered(tmp_path, monkeypatch):
    """A registered disk 3 with slots A to E, and the pins and image finder that point at it."""
    slots = [(letter, _slot(DARK_START)) for letter in "ABCDE"]
    files = {"disk1": _adf(tmp_path / "r1.adf", "POD 1"), "disk2": _adf(tmp_path / "r2.adf", "POD 2"),
             "disk3": _adf(tmp_path / "r3.adf", "POD 3", slots)}
    images = {key: pathlib.Path(entry["path"]).read_bytes() for key, entry in files.items()}
    for key, entry in files.items():
        monkeypatch.setattr(route_darkness, f"DARKNESS_{key.upper()}_SHA256", entry["sha256"])
    monkeypatch.setattr(route_darkness, "_find_images",
                        lambda wanted: {key: ("registered", images[key]) for key in wanted})
    monkeypatch.setattr(route_darkness, "DARKNESS_RELOAD", _reload_title())
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return images


def _written_disk3(tmp_path, images, *, f=F_PLACE, g=G_PLACE, extra=(), names=NAMES,
                   name="written3.adf", dropped=None):
    disk = AmigaDisk(images["disk3"])
    if dropped:
        # No file can be deleted, so the disk is rebuilt without one registered slot.
        disk = AmigaDisk.blank("POD 3")
        disk.make_dir("/SAVE")
        for letter in "ABCDE":
            if letter != dropped:
                disk.write_file(f"/SAVE/savgam{letter}.sav", _slot(DARK_START))
    for letter, place in (("F", f), ("G", g)):
        disk.write_file(f"/SAVE/savgam{letter}.sav", _slot(place, names))
    for path, raw in extra:
        disk.write_file(path, raw)
    path = tmp_path / name
    disk.save(path)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _accept_summary(tmp_path, sha, *, success=True, accept=True, fetched=None):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"success": success, "accept": accept,
                                "fetched": {"disk3": {"sha256": fetched or sha}}}))
    return path


def _prepare_reload(tmp_path, disk, sha, summary, run_id="reload-run", **kw):
    return foundation.prepare(foundation.TITLES["darkness-reload"], run_id, specimen=disk,
                              specimen_sha256=sha, accept_summary=summary, **kw)


def test_reload_prepare_writes_the_manifest_from_slots_g_and_f(tmp_path, monkeypatch):
    images = _reload_registered(tmp_path, monkeypatch)
    disk, sha = _written_disk3(tmp_path, images)
    summary = _accept_summary(tmp_path, sha)
    manifest = json.loads(_prepare_reload(tmp_path, disk, sha, summary).read_text())
    assert manifest["title"] == "darkness-reload" and manifest["loaded_letter"] == "G"
    assert manifest["state_a"] == G_PLACE and manifest["names_a"] == NAMES
    assert manifest["other_letter"] == "F" and manifest["other_place"] == F_PLACE
    assert manifest["registered"] == {"accept_disk3": {"path": str(disk), "sha256": sha}}
    assert set(manifest["disks"]) == {"disk1", "disk2", "disk3"}
    assert manifest["disks"]["disk3"]["sha256"] == sha
    assert manifest["disks"]["disk3"]["path"] != str(disk)
    assert set(manifest["slot_sha256"]) == {"F", "G"}
    assert manifest["accept_summary"]["sha256"] == hashlib.sha256(summary.read_bytes()).hexdigest()
    assert foundation._title_inputs(manifest, _reload_title())[2] == "G"


@pytest.mark.parametrize("what,match", [
    ("hash", "disk 3 SHA-256 differs"),
    ("failed", "not a successful accept run"),
    ("not accept", "not a successful accept run"),
    ("other hash", "another disk"),
    ("extra file", "registered disk 3 plus slots F and G"),
    ("changed file", "registered disk 3 plus slots F and G"),
    ("missing file", "registered disk 3 plus slots F and G"),
    ("other party", "names another party"),
    ("one place", "at one place"),
])
def test_reload_prepare_blocks(tmp_path, monkeypatch, what, match):
    images = _reload_registered(tmp_path, monkeypatch)
    options = {"extra file": {"extra": [("/SAVE/notes.dat", b"x")]},
               "missing file": {"dropped": "A"},
               "other party": {"names": ["OTHER", "PARTY"]},
               "one place": {"g": F_PLACE}}.get(what, {})
    disk, sha = _written_disk3(tmp_path, images, **options)
    if what == "changed file":
        changed = AmigaDisk(disk.read_bytes())
        changed.write_file("/SAVE/savgamA.sav", b"another byte string")
        changed.save(disk)
        sha = hashlib.sha256(disk.read_bytes()).hexdigest()
    summary_args = {"failed": {"success": False}, "not accept": {"accept": False},
                    "other hash": {"fetched": "0" * 64}}.get(what, {})
    summary = _accept_summary(tmp_path, sha, **summary_args)
    with pytest.raises(winuaesession.RouteError, match=match):
        _prepare_reload(tmp_path, disk, "1" * 64 if what == "hash" else sha, summary)
    assert not (tmp_path / ".cache" / "wish" / "acceptance" / "679" / "reload-run").exists()


def test_prepare_requires_the_reload_inputs_only_for_the_reload_title(tmp_path):
    with pytest.raises(winuaesession.RouteError, match="needs the disk 3"):
        foundation.prepare(foundation.TITLES["darkness-reload"], "x", specimen=tmp_path / "a")
    with pytest.raises(winuaesession.RouteError, match="takes no disk 3 hash"):
        foundation.prepare(foundation.DARKNESS, "x", specimen_sha256="0" * 64)
    with pytest.raises(winuaesession.RouteError, match="takes no disk 3 hash"):
        foundation.prepare(foundation.POOL, "x", accept_summary=tmp_path / "s.json")


def test_reload_command_runs_the_reload_and_prints_its_verdicts(tmp_path, monkeypatch, capsys):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda path: ("guards", str(path)))
    args = _measure_args(tmp_path, "--guards", "g.json", "--identity", "i.json")
    args[0], args[2] = "reload", "darkness-reload"
    args[args.index("--title") + 1] = "darkness-reload"
    assert foundation.main(args) == 0
    kw = called.calls[-1]
    assert kw["reload"] is True and "accept" not in kw and kw["title"] is foundation.DARKNESS_RELOAD
    assert kw["guard"] == ("guards", "g.json") and kw["identity"] == ("guards", "i.json")


def _reload_manifest_without(tmp_path, edit):
    path = _reload_manifest(tmp_path)
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))
    return path


@pytest.mark.parametrize("edit,match", [
    (lambda d: d.pop("other_letter"), "manifest lacks 'other_letter'"),
    (lambda d: d.pop("other_place"), "manifest lacks 'other_place'"),
    (lambda d: d["state_a"].pop("x"), "manifest lacks 'x'"),
    (lambda d: d["other_place"].pop("facing"), "manifest lacks 'facing'"),
    (lambda d: d.update(other_place=7), "reload place is not a mapping"),
    (lambda d: d.update(other_letter="H"), "holds no slot H to compare"),
], ids=["other_letter", "other_place", "state_a x", "other_place facing", "not a mapping",
        "other slot absent"])
def test_reload_blocks_a_manifest_that_cannot_be_compared_before_the_claim(
        tmp_path, clock, edit, match):
    guest = ReloadGuest(clock)
    path = _reload_manifest_without(tmp_path, edit)
    with pytest.raises(winuaesession.RouteError, match=match):
        foundation.run_recon(path, guest=guest, guard=_reload_guard(guest), identity=_IdentityMap(),
                        holder="wish679-test", audio_proof=_audio_proof(tmp_path),
                        title=_reload_title(), reload=True)
    assert guest.calls == []


@pytest.mark.parametrize("disk", ["disk1", "disk2"])
def test_reload_fails_when_the_game_changes_disk_1_or_2(tmp_path, clock, disk):
    def spoil(guest):
        remote = next(r for r in guest.remote if r.endswith(f"-{disk}.adf"))
        raw = bytearray(guest.remote[remote])
        raw[-1] ^= 0xFF
        guest.remote[remote] = bytes(raw)
    guest = ReloadGuest(clock, spoil=spoil)
    _, result = _reload_run(tmp_path, clock, guest=guest)
    assert result["completed"] is True and result["reload"]["shown"] is True
    assert result["disks_unchanged"][disk] is False and result["success"] is False


RECORDED = {"sha": "0123456789abcdef", "dirty": ["notes.txt"]}


def _record_state(monkeypatch):
    monkeypatch.setattr(foundation.evidence, "git_state", lambda repo: dict(RECORDED))
    monkeypatch.setattr(foundation.sys, "argv", ["acceptance.py", "--issue", "679", "--run", "x"])


def _summary(tmp_path):
    return json.loads((tmp_path / "recon1" / "summary.json").read_text())


def _assert_recorded(tmp_path, result):
    assert result["sha"] == RECORDED["sha"] and result["dirty"] == RECORDED["dirty"]
    assert result["argv"] == ["--issue", "679", "--run", "x"]
    summary = _summary(tmp_path)
    assert {k: summary[k] for k in ("sha", "dirty", "argv")} == {
        "sha": RECORDED["sha"], "dirty": RECORDED["dirty"],
        "argv": ["--issue", "679", "--run", "x"]}


def test_an_accept_run_summary_records_the_repository_state_and_arguments(
        tmp_path, clock, monkeypatch):
    _record_state(monkeypatch)
    _, result = _run(tmp_path, clock)
    _assert_recorded(tmp_path, result)


def test_a_measure_run_summary_records_the_repository_state_and_arguments(
        tmp_path, clock, monkeypatch):
    _record_state(monkeypatch)
    _, result = _run(tmp_path, clock, accept=False, measure=True)
    _assert_recorded(tmp_path, result)


def test_a_reload_run_summary_records_the_repository_state_and_arguments(
        tmp_path, clock, monkeypatch):
    _record_state(monkeypatch)
    _, result = _reload_run(tmp_path, clock)
    _assert_recorded(tmp_path, result)


def test_a_run_that_stops_early_still_records_the_repository_state_and_arguments(
        tmp_path, clock, monkeypatch):
    _record_state(monkeypatch)

    class Stops(TitleGuest):
        def press(self, holder, key, timeout=None):
            raise RuntimeError("the guest stopped answering")

    _, result = _run(tmp_path, clock, guest=Stops(clock, save_key="save"))
    assert result["error"] and result["completed"] is False and result["success"] is False
    _assert_recorded(tmp_path, result)


@pytest.mark.parametrize("module", ["route_pool", "route_curse", "route_darkness"])
def test_a_title_route_module_imports_without_the_runners(module):
    program = (
        f"import sys; import tools.amiga.{module}; "
        "sys.exit(int(any(name in sys.modules for name in ("
        "'tools.amiga.acceptance', "
        "'tools.amiga.screens'))))")
    done = subprocess.run([sys.executable, "-c", program],
                          cwd=pathlib.Path(__file__).resolve().parents[2])
    assert done.returncode == 0


def test_importing_acceptance_alone_leaves_guardmaps_unimported():
    program = ("import sys; import tools.amiga.acceptance; "
              "sys.exit(int('tools.amiga.guardmaps' in sys.modules))")
    done = subprocess.run([sys.executable, "-c", program],
                          cwd=pathlib.Path(__file__).resolve().parents[2])
    assert done.returncode == 0


def test_the_command_line_help_exits_0_both_ways_and_no_subcommand_exits_2():
    repo = pathlib.Path(__file__).resolve().parents[2]
    for argv in (["tools/amiga/acceptance.py", "--help"],
                ["-m", "tools.amiga.acceptance", "--help"]):
        done = subprocess.run([sys.executable, *argv], cwd=repo, capture_output=True)
        assert done.returncode == 0
    with pytest.raises(SystemExit) as exc:
        foundation.main([])
    assert exc.value.code == 2


def test_prepare_blocks_a_run_id_with_a_space_before_touching_anything(capsys):
    assert foundation.main(["prepare", "--title", "pool", "--run-id", "a b"]) == 2
    assert capsys.readouterr().err == (
        "acceptance: run id must use letters, digits, dot, underscore or hyphen\n")


def test_prepare_blocks_an_unknown_title_through_argparse():
    with pytest.raises(SystemExit) as exc:
        foundation.main(["prepare", "--title", "unknown", "--run-id", "x"])
    assert exc.value.code == 2


class _RecordingGuest:
    """A `WinGuest` stand-in that records every call it is given, and makes none itself."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


@pytest.mark.parametrize("reaches_title,stale_log,timing,intermediate", [
    (True, False, "normal", None), (False, False, "normal", None),
    (True, "missing", "normal", None), (True, "other", "normal", None),
    (False, False, "exhausted", None),
    (False, False, "probe_boundary", None),
    (True, False, "normal", "credits"),
    (False, False, "normal", "credits"),
    (True, False, "normal", "party_menu"),
])
def test_diagnose_uses_private_config_and_cleans_up_without_game_input(
        tmp_path, monkeypatch, clock, reaches_title, stale_log, timing, intermediate):
    title = dataclasses.replace(
        foundation.route_silver_blades.published_title("A"),
        read_slot=_read_slot, slot_letters=_letters, slot_files=_files)
    disks = {"df0": _adf(tmp_path / "df0.adf", "ONE", [("A", _slot(START))]),
             "df1": _adf(tmp_path / "df1.adf", "TWO")}
    registered = {"published": _adf(tmp_path / "published.adf", "ONE",
                                    [("A", _slot(START))]),
                  "disk_two": _adf(tmp_path / "registered-disk2.adf", "TWO")}
    for key, registered_key in (("df0", "published"), ("df1", "disk_two")):
        pathlib.Path(registered[registered_key]["path"]).write_bytes(
            pathlib.Path(disks[key]["path"]).read_bytes())
        registered[registered_key]["sha256"] = disks[key]["sha256"]
    manifest = {"mode": "published_disk_one", "issue": "677", "title": "ssb",
                "source_port": "c64", "loaded_letter": "A", "state_a": START,
                "names_a": NAMES, "disks": disks,
                "registered": registered}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(foundation, "_published_manifest", lambda *_: (manifest, title))
    monkeypatch.setattr(foundation, "_white_screen", lambda p: p.read_bytes() == b"white",
                        raising=False)

    class Guest(WinuaeLaneNames):
        def __init__(self):
            self.calls = []
            self.remote = {}
            self.started = False
            self.probe_timeouts = []

        def claim(self, holder, timeout):
            self.calls.append("claim")
            return f"ok claimed by {holder}"

        def put(self, local, remote, timeout):
            self.calls.append("put")
            self.remote[remote] = pathlib.Path(local).read_bytes()

        def stage_private_config(self, holder, timeout):
            self.calls.append("config")
            return {"path": f"C:\\Amiga\\configs\\wish705-{holder}.uae", "sha256": "abc"}

        def start(self, holder, *drives, timeout, options, config):
            self.calls.append("start")
            self.started = True
            assert config == f"C:\\Amiga\\configs\\wish705-{holder}.uae"
            assert drives == tuple(self.staged_path(k) for k in ("df0", "df1"))
            return "ok pid=123"

        def lane(self, holder, timeout):
            self.calls.append("lane")
            return 1

        def staged_path(self, key):
            return next(p for p in self.remote if p.endswith(f"-{key}.adf"))

        def diagnose(self, holder, section, key, timeout, address=None):
            self.calls.append("diagnose")
            if section == "DBG":
                self.probe_timeouts.append(timeout)
            if section == "CFG":
                value = ("directdraw" if key == "gfx_api" else
                         self.staged_path("df0" if key == "floppy0" else "df1")
                         .replace("/", "\\"))
                return {"reply": f"200 \n{value}"}
            value = (b"\0" * 4 + (0x1000).to_bytes(4, "big") + b"\0" * 8
                     if address == 0 else
                     b"\0" * 8 + b"\0\0\0\x01" + b"\0\0\0\x02")
            # The memory parser needs the debugger's address and eight words.
            return {"reply": f"{address:08x} " + " ".join(
                value[i:i + 2].hex() for i in range(0, len(value), 2)) + " ........"}

        def grab(self, state, raw, crop, timeout):
            self.calls.append("grab")
            if timing == "exhausted":
                clock.now = 1700
            elif timing == "probe_boundary":
                clock.now = 1299
            raw.write_bytes(b"raw")
            crop.write_bytes(
                intermediate.encode() if intermediate and 1010 <= clock.now < 1012 else
                b"title" if reaches_title and clock.now >= 1130 else b"white")
            return True

        def status(self, timeout):
            self.calls.append("status")
            self.probe_timeouts.append(timeout)
            return "pid=123 responding=True"

        def stop(self, holder, timeout):
            self.calls.append("stop")
            self.stop_timeout = timeout
            if timeout < 12:
                raise OSError("stop timed out before the guest's 10-second wait")
            return "ok stopped"

        def get(self, remote, local, timeout):
            self.calls.append("get")
            if remote == foundation.BOOT_LOG.format(lane=1):
                assert self.started, "the boot log was read before the start"
                if stale_log == "missing":
                    raise foundation.RouteError("winvm get failed: the lane has no boot log")
                if stale_log == "other":
                    local.write_text("previous boot log")
                else:
                    invocation = (f"'-f C:\\Amiga\\configs\\wish705-wish705-test.uae "
                                  f"-s floppy0={self.staged_path('df0').replace('/', chr(92))} "
                                  f"-s floppy1={self.staged_path('df1').replace('/', chr(92))}'")
                    local.write_text("new boot log " + invocation)
            else:
                local.write_bytes(self.remote[remote])

        def remove_private_config(self, holder, timeout):
            self.calls.append("config-remove")
            return "ok private config removed"

        def release(self, holder, timeout):
            self.calls.append("release")
            return "ok released"

    guest = Guest()
    class Guard:
        rules = {"title": {}, "credits": {}, "party_menu": {}}

        def __contains__(self, state):
            return state in self.rules

        def __call__(self, state, crop):
            return crop.read_bytes() == state.encode()

    result = foundation.run_recon(
        path, guest=guest, holder="wish705-test", audio_proof=_audio_proof(tmp_path),
        title=title, guard=Guard(), diagnose=True, published_disk_one=True,
        published_name="ssb", deadline_seconds=600, boot_limit=300)
    assert result["success"] is (reaches_title and not stale_log and timing == "normal"
                                 and intermediate != "party_menu"), (
                                               result["error"], result.get("boot_log_error"),
                                               result.get("stop_error"),
                                               result.get("config_remove_error"),
                                               result.get("white_probe"))
    assert result["completed"] is (reaches_title and timing == "normal"
                                   and intermediate != "party_menu")
    if intermediate:
        assert [event.get("recognized") for event in result["events"] if
                event.get("recognized")] == (["credits", *(["title"] if reaches_title else [])]
                                             if intermediate == "credits"
                                             else ["party_menu"])
    if intermediate == "party_menu":
        assert result["error"] == "RouteError: recognized party_menu before the title"
    if intermediate == "credits" and not reaches_title:
        assert result["error"] == "RouteError: title screen was not recognized within 300s"
    if timing == "normal" and intermediate != "party_menu":
        assert result["white_probe"]["first"]["execbase"] == 0x1000
        assert result["white_probe"]["status"].startswith("pid=123")
    if stale_log == "missing":
        assert result["boot_log_fresh"] is False
        assert result["boot_log_error"] == "RouteError: winvm get failed: the lane has no boot log"
    if stale_log == "other":
        assert result["boot_log_matches_start"] is False
        assert result["boot_log_error"] == "boot log names another launch"
    assert result["lane"] == 1
    assert guest.calls.index("start") < guest.calls.index("lane") < guest.calls.index("get")
    if timing == "exhausted":
        assert result["cleanup_after_deadline"] is True
        assert guest.stop_timeout >= 20
        assert result["stop"] == "ok stopped"
        assert result["config_removed"] == "ok private config removed"
        assert result["release"] == "ok released"
    if timing == "probe_boundary":
        assert result["white_probe"]["first"]["execbase"] == 0x1000
        assert max(guest.probe_timeouts) <= 1
        assert "boot deadline" in result["error"]
    assert result["df0_fetched_unchanged"] and result["df1_fetched_unchanged"]
    assert guest.calls.index("config") < guest.calls.index("start")
    assert guest.calls.index("stop") < guest.calls.index("config-remove") < guest.calls.index("release")
    assert guest.calls.index("get") < guest.calls.index("release")
    assert "press" not in guest.calls and "insert" not in guest.calls
    if timing == "normal":
        assert result["elapsed_seconds"] <= 300


def test_diagnose_cli_dispatches_only_published_silver_blades(tmp_path, monkeypatch):
    manifest = tmp_path / "prepare.json"
    manifest.write_text("{}")
    guards = tmp_path / "guards.json"
    guards.write_text("{}")
    audio = _audio_proof(tmp_path)
    observed = []
    monkeypatch.setattr(foundation, "_published_manifest", lambda *_: (
        {"loaded_letter": "A"}, foundation.route_silver_blades.published_title("A")))
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda p: p)
    monkeypatch.setattr(foundation, "_summary", lambda *a: "summary")

    def run(*args, **kwargs):
        observed.append(kwargs)
        return {"success": True, "error": ""}

    monkeypatch.setattr(foundation, "run_recon", run)
    code = foundation.main(["diagnose", "--title", "ssb", "--published-disk-one",
                            "--manifest", str(manifest), "--guards", str(guards),
                            "--audio-proof", str(audio), "--attempt", "gfx705-test",
                            "--boot-limit", "300", "--deadline", "600"])
    assert code == 0
    assert len(observed) == 1
    assert observed[0]["diagnose"] is True and observed[0]["boot_limit"] == 300
    assert observed[0]["title"].issue == "677"
    observed.clear()
    assert foundation.main(["diagnose", "--title", "curse", "--published-disk-one",
                            "--manifest", str(manifest), "--guards", str(guards),
                            "--audio-proof", str(audio)]) == 2
    assert not observed


@pytest.mark.parametrize("boot_failed", [False, True])
def test_diagnose_cli_reports_preboot_failure_and_dirty_private_config(
        tmp_path, monkeypatch, capsys, boot_failed):
    error = (("RouteError: winvm ssh failed: config-hash is not in the guest "
              "launcher's ValidateSet") if boot_failed else "")
    remove_error = ("RouteError: winvm ssh failed: config-remove is not in the "
                    "guest launcher's ValidateSet")
    manifest = tmp_path / "prepare.json"
    manifest.write_text("{}")
    guards = tmp_path / "guards.json"
    guards.write_text("{}")
    audio = _audio_proof(tmp_path)
    monkeypatch.setattr(foundation, "_published_manifest", lambda *_: (
        {"loaded_letter": "A"}, foundation.route_silver_blades.published_title("A")))
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda p: p)
    monkeypatch.setattr(foundation, "run_recon", lambda *args, **kwargs: {
        "diagnose": True, "success": False, "completed": False, "error": error,
        "config_remove_error": remove_error, "remote_config_dirty": True,
        "remote_config_path": r"C:\Amiga\configs\wish705-wish705-test.uae",
    })

    code = foundation.main([
        "diagnose", "--title", "ssb", "--published-disk-one", "--manifest", str(manifest),
        "--guards", str(guards), "--audio-proof", str(audio), "--attempt", "gfx705-test",
    ])

    assert code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["error"] == (error or remove_error)
    assert printed["config_remove_error"] == remove_error
    assert printed["remote_config_dirty"] is True
    assert printed["remote_config_path"].endswith("wish705-wish705-test.uae")
    assert printed["unguarded"] == []


@pytest.mark.parametrize("failure,expected", [
    ({"stop_error": "OSError: stop timed out"}, "OSError: stop timed out"),
    ({"fetch_df0_error": "OSError: DF0 fetch failed"}, "OSError: DF0 fetch failed"),
    ({"boot_log_error": "RouteError: stale boot log"}, "RouteError: stale boot log"),
    ({"df0_fetched_unchanged": False}, "diagnostic failed; see"),
    ({"gfx_api_rejected": True}, "diagnostic failed; see"),
])
def test_diagnose_summary_names_cleanup_failure_or_points_to_full_result(
        tmp_path, failure, expected):
    result = {"diagnose": True, "success": False, "error": "", **failure}
    printed = json.loads(foundation._summary(result, tmp_path / "prepare.json", "probe"))
    assert expected in printed["error"]
    if expected == "diagnostic failed; see":
        assert printed["summary"] in printed["error"]


def test_diagnose_records_config_hash_failure_and_failed_cleanup(tmp_path):
    disks = {key: tmp_path / f"{key}.adf" for key in ("df0", "df1")}
    for key, path in disks.items():
        path.write_bytes(key.encode())
    manifest = tmp_path / "prepare.json"
    manifest.write_text(json.dumps({"disks": {
        key: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for key, path in disks.items()}}))

    class Guest(WinuaeLaneNames):
        def __init__(self):
            self.remote = {}

        def claim(self, holder, timeout):
            return f"ok claimed by {holder}"

        def get(self, remote, local, timeout):
            # No start, so no lane and no boot log to read.
            local.write_bytes(self.remote[remote])

        def put(self, local, remote, timeout):
            self.remote[remote] = local.read_bytes()

        def stage_private_config(self, holder, timeout):
            raise foundation.RouteError("config-hash rejected by guest ValidateSet")

        def remove_private_config(self, holder, timeout):
            raise foundation.RouteError("config-remove rejected by guest ValidateSet")

        def release(self, holder, timeout):
            return f"ok released by {holder}"

    result = foundation._run_diagnose(
        manifest, json.loads(manifest.read_text()),
        foundation.route_silver_blades.published_title("A"), disks, Guest(),
        guard=None, holder="wish705-test", audio_proof=tmp_path / "mute.json",
        attempt="preboot-failure", deadline=600, boot_limit=300)

    assert result["error"] == "RouteError: config-hash rejected by guest ValidateSet"
    assert result["config_remove_error"] == (
        "RouteError: config-remove rejected by guest ValidateSet")
    assert result["remote_config_dirty"] is True
    assert result["remote_config_path"] == r"C:\Amiga\configs\wish705-wish705-test.uae"
    assert result["release"] == "ok released by wish705-test"
    assert result["df0_fetched_unchanged"] and result["df1_fetched_unchanged"]
    assert json.loads((tmp_path / "preboot-failure" / "summary.json").read_text()) == result


def test_measure_blocks_a_missing_disk2_prompt_guard_through_main_before_any_guest_call(
        tmp_path, monkeypatch, capsys):
    guest = _RecordingGuest()
    monkeypatch.setattr(foundation, "WinGuest", lambda: guest)
    guards = tmp_path / "guards.json"
    guards.write_text("{}")
    argv = ["measure", "--title", "darkness", "--manifest", str(tmp_path / "prepare.json"),
           "--audio-proof", str(tmp_path / "mute.json"), "--attempt", "measure1",
           "--guards", str(guards)]
    assert foundation.main(argv) == 2
    assert "acceptance: " in capsys.readouterr().err
    assert guest.calls == []


def test_accept_blocks_an_identity_map_missing_sheet_through_main_before_any_guest_call(
        tmp_path, monkeypatch, capsys):
    guest = _RecordingGuest()
    monkeypatch.setattr(foundation, "WinGuest", lambda: guest)
    guards = tmp_path / "guards.json"
    guards.write_text("{}")
    identity = tmp_path / "identity.json"
    identity.write_text("{}")
    argv = ["accept", "--title", "pool", "--manifest", str(tmp_path / "prepare.json"),
           "--audio-proof", str(tmp_path / "mute.json"), "--attempt", "accept1",
           "--guards", str(guards), "--identity", str(identity)]
    assert foundation.main(argv) == 2
    assert "acceptance: " in capsys.readouterr().err
    assert guest.calls == []


@pytest.mark.parametrize("title, extra", [
    ("pool", []),
    ("curse", ["--published-disk-one", "--preserve-specimen"]),
])
def test_main_blocks_specimen_issue_without_a_substituted_preservation(
        tmp_path, capsys, monkeypatch, title, extra):
    for name in ("g", "i"):
        (tmp_path / name).write_text("{}")
    monkeypatch.setattr(foundation, "_published_manifest",
                        lambda path, name: ({"loaded_letter": "A"}, None))
    monkeypatch.setattr(foundation, "_published_title", lambda name, letter: None)
    argv = ["accept", "--title", title, "--manifest", str(tmp_path / "prepare.json"),
            "--audio-proof", str(tmp_path / "audio"), "--guards", str(tmp_path / "g"),
            "--identity", str(tmp_path / "i"), "--attempt", "a1",
            "--specimen-issue", "#631 (a title)", *extra]
    assert foundation.main(argv) == 2
    assert "--specimen-issue" in capsys.readouterr().err


def _published_report(tmp_path, monkeypatch, *, name, issue, place=None):
    """A Save As report for a synthetic C64 source pinned under `issue`, and its inputs."""
    key, exe, ext, make = {
        "curse": (route_curse.CURSE_KEY, "/Curse", "dat", synthetic_amiga.synthetic_curse),
        "ssb": (foundation.route_silver_blades.TITLE, "/Secret", "sav",
                synthetic_amiga.synthetic_silver_blades),
    }[name]
    source = tmp_path / "party.D64"
    source.write_bytes(b"synthetic source")
    disk1 = tmp_path / "disk1.adf"
    one = synthetic_amiga.synthetic_disk_one(key)
    disk1.write_bytes(one.to_bytes())
    disk2 = tmp_path / "disk2.adf"
    disk2.write_bytes(AmigaDisk.blank("Disk2").to_bytes())
    published = tmp_path / "POOLSAVE.ADF"
    converted = AmigaDisk(one.to_bytes())
    converted.write_file(f"/SAVE/savgamA.{ext}",
                         make(("GUY DE VALOIS",)) if name == "ssb" else make(("CONVERTED",)))
    published.write_bytes(converted.to_bytes())
    source_sha = staging.sha256(source)
    image_sha = staging.sha256(published)
    monkeypatch.setitem(foundation.PUBLISHED_SOURCES_BY_ISSUE[issue], (name, "c64"), source_sha)
    monkeypatch.setitem(foundation.PUBLISHED_DISKS, name, (
        staging.sha256(disk1), staging.sha256(disk2), exe, "Disk1"))
    monkeypatch.setattr(foundation.scratch, "cache_dir",
                        lambda *parts: tmp_path.joinpath("cache", *map(str, parts)))
    if place is not None:
        monkeypatch.setattr(
            route_curse.amiga_savegame, "state_from_savegame",
            lambda _saved: type("State", (), place)())
    report = {
        "specimen": str(source), "specimen_sha256": source_sha,
        "amiga_disk1": str(disk1), "amiga_disk2": str(disk2), "c64_disks_dir": str(tmp_path),
        "save_as": {"source": str(source), "to": "amiga", "slot": "A",
                    "destination": str(published), "written": [str(published)],
                    "losses": [], "dropped": []},
        "written": [str(published)], "written_sha256": {"POOLSAVE.ADF": image_sha},
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    return path, source_sha


CURSE_START_640 = {"area": 1, "x": 7, "y": 13, "facing": 1}
CURSE_WORLD = {"area": 3, "x": 4, "y": 4, "facing": geo.NORTH}


def test_the_start_square_literal_is_the_one_the_driver_compares():
    start = areas.start_of(areas.CURSE_OF_THE_AZURE_BONDS)
    assert CURSE_START_640 == {"area": start.area, "x": start.arrival.x,
                               "y": start.arrival.y, "facing": start.arrival.facing}


def _manifest_with(tmp_path, monkeypatch, **changes):
    path, _ = _prepared(tmp_path, monkeypatch, "curse", "640")
    manifest = json.loads(path.read_text())
    for key, value in changes.items():
        if value is KeyError:
            del manifest[key]
        else:
            manifest[key] = value
    path.write_text(json.dumps(manifest))
    return path


@pytest.mark.parametrize("bad", ["false", "true", 0, 1, None])
def test_a_manifest_turn_about_that_is_not_a_bool_is_blocked(tmp_path, monkeypatch, bad):
    path = _manifest_with(tmp_path, monkeypatch, turn_about=bad)
    with pytest.raises(winuaesession.RouteError, match="not a boolean"):
        foundation._published_manifest(path, "curse")


def test_a_manifest_turn_about_that_disagrees_with_its_place_is_blocked(tmp_path, monkeypatch):
    path = _manifest_with(tmp_path, monkeypatch, turn_about=False)
    with pytest.raises(winuaesession.RouteError, match="disagrees with its recorded place"):
        foundation._published_manifest(path, "curse")


def test_a_manifest_place_that_disagrees_with_its_turn_about_is_blocked(tmp_path, monkeypatch):
    path = _manifest_with(tmp_path, monkeypatch, state_a=CURSE_WORLD)
    with pytest.raises(winuaesession.RouteError, match="disagrees with its recorded place"):
        foundation._published_manifest(path, "curse")


def test_a_manifest_without_turn_about_still_turns_only_for_letter_d(tmp_path, monkeypatch):
    path = _manifest_with(tmp_path, monkeypatch, turn_about=KeyError)
    _, title = foundation._published_manifest(path, "curse")
    assert title.turn != "about"


def test_prepare_under_640_files_the_run_under_640_and_turns_a_party_at_the_start_about(
        tmp_path, monkeypatch):
    report, _ = _published_report(tmp_path, monkeypatch, name="curse", issue="640",
                                  place=CURSE_START_640)
    from tools.amiga.acceptance import main  # noqa: PLC0415
    assert main(["prepare", "--title", "curse", "--run-id", "run640", "--published-disk-one",
                 "--issue", "640", "--saveas-report", str(report)]) == 0
    path = tmp_path / "cache" / "acceptance" / "640" / "run640" / "prepare.json"
    manifest = json.loads(path.read_text())
    assert manifest["issue"] == "640" and manifest["turn_about"] is True
    _, title = foundation._published_manifest(path, "curse")
    assert title.issue == "640" and title.turn == "about"


def test_prepare_leaves_a_curse_party_standing_in_the_world_unturned(tmp_path, monkeypatch):
    report, _ = _published_report(tmp_path, monkeypatch, name="curse", issue="640",
                                  place=CURSE_WORLD)
    path = foundation.prepare_published("curse", "runworld", report, "640")
    assert json.loads(path.read_text())["turn_about"] is False


def test_the_turn_comes_from_the_manifest_place_and_falls_back_to_the_letter():
    turned = foundation._published_title("curse", "A", issue="640", turn_about=True)
    keys = [key for key, _, _ in turned.route]
    first_move = next(i for i, (_, _, kind) in enumerate(turned.route) if kind == "move")
    assert ("NP2", "world", "turn") in turned.route[:first_move]
    assert turned.turn == "about" and turned.issue == "640"
    assert "NP2" not in [key for key, _, _ in
                         foundation._published_title("curse", "A", issue="640",
                                                     turn_about=False).route]
    assert "NP2" in [key for key, _, _ in foundation._published_title("curse", "D").route]
    assert "NP2" not in [key for key, _, _ in foundation._published_title("curse", "A").route]
    assert keys.count("NP2") == 1
    ssb = foundation._published_title("ssb", "A", issue="640", turn_about=True)
    assert ssb.turn == "about" and ssb.issue == "640"


def _prepared(tmp_path, monkeypatch, name, issue):
    report, source_sha = _published_report(tmp_path, monkeypatch, name=name, issue=issue,
                                           place=CURSE_START_640 if name == "curse" else None)
    path = foundation.prepare_published(name, f"run{issue}", report, issue)
    return path, source_sha


def test_a_published_manifest_is_checked_against_its_own_issues_pins(tmp_path, monkeypatch):
    path, source_sha = _prepared(tmp_path, monkeypatch, "curse", "640")
    foundation._published_manifest(path, "curse")
    manifest = json.loads(path.read_text())
    # The synthetic source is pinned under 640 only; filed as 677 it is an unknown source.
    manifest["issue"] = "677"
    path.write_text(json.dumps(manifest))
    with pytest.raises(winuaesession.RouteError, match="pinned specimen"):
        foundation._published_manifest(path, "curse")
    # And the real 677 pin does not pass under 640.
    manifest["issue"] = "640"
    manifest["source_sha256"] = next(iter(foundation.PUBLISHED_SOURCES[("curse", "c64")]))
    path.write_text(json.dumps(manifest))
    with pytest.raises(winuaesession.RouteError, match="pinned specimen"):
        foundation._published_manifest(path, "curse")
    with pytest.raises(winuaesession.RouteError, match="no pinned sources"):
        foundation.prepare_published("curse", "x", tmp_path / "report.json", "999")


def test_the_silver_blades_continue_page_is_answered_up_to_the_published_limit_in_one_wait(
        tmp_path, clock):
    rows = foundation.route_silver_blades.published_title("A").interstitials
    limit = foundation.route_silver_blades.PUBLISHED_CONTINUE_LIMIT
    assert limit >= 9  # the opening scene's pages before the treasure screen
    looks = []

    def picker(_path):
        looks.append(1)
        return len(looks) >= limit + 5

    guard = MapGuard(states=("title", *TITLE_STATES, "continue"), on={
        "load_picker": picker, "continue": lambda _path: 0 < len(looks) < limit + 5})
    guest, _ = _title_run(tmp_path, clock, rows, guard)
    assert _keys(guest).count("RET") == limit


def _title_run(tmp_path, clock, rows, guard):
    from tests.amiga import test_amigaacceptance_title as title_tests  # noqa: PLC0415
    make_title, title_run = title_tests.make_title, title_tests._run
    return title_run(tmp_path, clock, title=make_title(interstitials=rows), guard=guard)


def test_a_640_manifest_registers_its_specimen_under_640(tmp_path, specimen_root):
    manifest = tmp_path / "run" / "prepare.json"
    fetched = manifest.parent / "accept1" / "fetched-df0.adf"
    fetched.parent.mkdir(parents=True)
    fetched.write_bytes(b"game-written DF0")
    saved = foundation._preserve_published(manifest, "accept1", "curse", fetched, "640")
    assert "wish-640-curse-" in saved["path"]
    text = pathlib.Path(saved["provenance"]).read_text()
    assert "#640 (A Curse or Silver Blades party saved before BEGIN ADVENTURING" in text


# ---- A Silver Blades party that has not set out: opening pages, a treasure screen, then the world.

OPENING_TAIL = [
    (None, "treasure_bar", "answer"), ("E", "treasure", "key"), ("N", "world", "key"),
    ("NP8", "world", "move"), ("NP8", "world", "move"),
    ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
    ("F", "exit_game", "write"), ("N", "camp", "key"),
]
SSB_START = {"area": 16, "x": 3, "y": 3, "facing": geo.SOUTH}
OPENING_KEYS = (["P", "L", "A", "V", "E", "S", "C", "B"] + ["RET"] * 9 + ["E", "N"]
                + ["RET"] * 3 + ["NP8", "NP8", "E", "S", "F", "N"])
# Screen after each (screen, key); RET on a page moves to the next page or, at the last, on.
SSB_SCREENS = {
    ("title", "P"): "party_menu", ("party_menu", "L"): "load_picker",
    ("load_picker", "A"): "loaded_menu", ("loaded_menu", "V"): "sheet",
    ("sheet", "E"): "loaded_menu", ("loaded_menu", "S"): "save_picker",
    ("save_picker", "C"): "loaded_menu", ("loaded_menu", "B"): "journal",
    ("treasure_bar", "E"): "treasure", ("world", "NP8"): "world", ("world", "E"): "camp",
    ("camp", "S"): "camp_save_picker", ("camp_save_picker", "F"): "exit_game",
    ("exit_game", "N"): "camp",
}
PAGE_SECONDS = 25.0  # a page is answered 16 to 25 seconds after the last one


class OpeningGuest(TitleGuest):
    """The game's screen after each key, with the opening scene's pages taking their time."""

    def __init__(self, clock, *, unguarded_world=False):
        super().__init__(clock, save_key="df0")
        self.screen, self.pages, self.then = "title", 0, None
        self.unguarded_world = unguarded_world

    def pages_of(self, count, then):
        self.screen, self.pages, self.then = "continue", count, then

    def press(self, holder, key, timeout=None):
        super().press(holder, key, timeout=timeout)
        if key == "RET" and self.screen == "continue":
            self.clock.now += PAGE_SECONDS
            self.pages -= 1
            if self.pages == 0:
                self.screen = self.then
        elif (self.screen, key) == ("treasure", "N"):
            self.pages_of(3, "smudge" if self.unguarded_world else "world")
        else:
            self.screen = SSB_SCREENS.get((self.screen, key), self.screen)

    def capture(self, state, raw, cropped, timeout=None):
        raw.write_bytes(b"raw")
        cropped.write_bytes(self.screen.encode())

    def grab(self, state, raw, cropped, timeout=None):
        self.calls.append(("grab", state))
        self.capture(state, raw, cropped)
        return True


class ScreenNameGuard:
    """A guard that recognises a screen by the name the fake guest wrote into its crop."""

    states = {"title", "party_menu", "load_picker", "loaded_menu", "sheet", "save_picker",
              "journal", "continue", "treasure_bar", "treasure", "world", "camp",
              "camp_save_picker", "exit_game"}

    def __contains__(self, state):
        return state in self.states

    def __call__(self, state, path):
        return path.read_bytes() == state.encode()


def _opening_accept(tmp_path, monkeypatch, clock, *, title=None, guest=None):
    """Accept a party that has not set out, against the fake guest above."""
    def read_slot(disk, letter):
        return {**_read_slot(disk, letter), "clock": "00:01" if letter == "F" else "00:00"}

    title = dataclasses.replace(
        title or foundation.route_silver_blades.published_title(
            "A", items_screen=False, opening_scene=True),
        read_slot=read_slot, slot_letters=_letters, slot_files=_files)
    slots = [("A", _slot(SSB_START))]
    disks = {"df0": _adf(tmp_path / "df0.adf", "ONE", slots),
             "df1": _adf(tmp_path / "df1.adf", "TWO")}
    registered = {"source": _adf(tmp_path / "source.adf", "SOURCE"),
                  "report": _adf(tmp_path / "report.adf", "REPORT"),
                  "published": _adf(tmp_path / "published.adf", "ONE", slots),
                  "disk_one": _adf(tmp_path / "disk-one.adf", "ONE", slots),
                  "disk_two": _adf(tmp_path / "disk-two.adf", "TWO")}
    (tmp_path / "published.adf").write_bytes((tmp_path / "df0.adf").read_bytes())
    registered["published"]["sha256"] = disks["df0"]["sha256"]
    (tmp_path / "disk-two.adf").write_bytes((tmp_path / "df1.adf").read_bytes())
    registered["disk_two"]["sha256"] = disks["df1"]["sha256"]
    manifest = {"mode": "published_disk_one", "issue": "640", "title": "ssb",
                "source_port": "c64", "loaded_letter": "A", "state_a": SSB_START,
                "names_a": NAMES, "clock_a": "00:00", "disks": disks,
                "registered": registered, "expected_after": None}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(foundation, "_published_manifest", lambda *_: (manifest, title))
    guest = guest or OpeningGuest(clock)
    guest.place = dict(SSB_START)
    answers = []

    def answer(_holder, _adf_path, _timeout):
        answers.append(1)
        guest.pages_of(9, "treasure_bar")
        return 0, "answered"

    original_press = guest.press

    def press(holder, key, timeout=None):
        original_press(holder, key, timeout=timeout)
        if key == "F":
            guest._write("F", guest.place)

    guest.press = press
    result = foundation.run_recon(
        path, guest=guest, holder="wish640-test", audio_proof=_audio_proof(tmp_path),
        title=title, guard=ScreenNameGuard(), identity=_IdentityMap(), accept=True,
        published_disk_one=True, published_name="ssb", journal_python="/usr/bin/python3",
        preflight=lambda _python: None, answer=answer)
    return guest, result, answers


def test_the_opening_scene_route_replaces_only_the_answer_wait_and_adds_no_turn():
    blades = foundation.route_silver_blades
    title = blades.published_title("A", items_screen=False, opening_scene=True)
    at = title.route.index(("B", "journal", "key")) + 1
    assert list(title.route[at:]) == OPENING_TAIL
    assert title.turn is None
    assert {"treasure_bar", "treasure", "world"} <= title.strict
    assert title.wait_limits == {"treasure_bar": 300.0}
    assert blades.PUBLISHED_CONTINUE_LIMIT >= 9
    # Every other route keeps the answer wait for `world`, its two moves and no per-state limit.
    ordinary = blades.published_title("A", items_screen=False)
    assert (None, "world", "answer") in ordinary.route and ordinary.wait_limits == {}
    assert "world" not in ordinary.strict
    assert not any(kind == "turn" for _, _, kind in
                   blades.published_title("D", opening_scene=True).route)


def test_the_opening_route_is_chosen_by_the_saves_set_out_flag_not_the_place():
    assert foundation._opening_scene("ssb", {"not_set_out": True}) is True
    # A party that has set out and was saved on the start square gets no opening scene.
    assert foundation._opening_scene("ssb", {"not_set_out": False, "place": SSB_START}) is False
    assert foundation._opening_scene("curse", {"not_set_out": True}) is False
    assert foundation._opening_scene("ssb", None) is False


@pytest.mark.parametrize("not_set_out", [True, False])
def test_a_prepared_party_on_the_start_square_gets_the_opening_scene_only_if_it_has_not_set_out(
        tmp_path, monkeypatch, not_set_out):
    monkeypatch.setattr(foundation.route_silver_blades.world_state, "has_not_set_out",
                        lambda _state: not_set_out)
    path = _prepared_published(tmp_path, monkeypatch, members_items=0)
    manifest, title = foundation._published_manifest(path, "ssb")
    assert manifest["state_a"] == SSB_START
    assert manifest["opening_scene"] is not_set_out
    assert bool(title.wait_limits) is not_set_out


def test_a_prepared_party_records_and_uses_the_route_its_place_calls_for(
        tmp_path, monkeypatch):
    path = _prepared_published(tmp_path, monkeypatch, members_items=0)
    manifest, title = foundation._published_manifest(path, "ssb")
    expected = foundation._opening_scene("ssb", {"not_set_out": manifest["opening_scene"]})
    assert manifest["opening_scene"] is expected
    assert bool(title.wait_limits) is expected
    manifest["opening_scene"] = not expected
    path.write_text(json.dumps(manifest))
    with pytest.raises(winuaesession.RouteError, match="opening_scene disagrees"):
        foundation._published_manifest(path, "ssb")


def test_the_opening_accept_presses_the_exact_keys_and_answers_twelve_pages(
        tmp_path, monkeypatch, clock):
    guest, result, answers = _opening_accept(tmp_path, monkeypatch, clock)
    assert result["error"] == "" and result["success"] is True, result["read"]["verdicts"]
    assert _keys(guest) == OPENING_KEYS
    assert "Y" not in _keys(guest) and len(answers) == 1
    events = [json.loads(line) for line in
              (tmp_path / "recon1" / "run.jsonl").read_text().splitlines()]
    assert sum(e.get("event") == "interstitial" and e.get("screen") == "continue"
               for e in events) == 12
    assert guest.place == {"area": 16, "x": 3, "y": 5, "facing": geo.SOUTH}


def test_the_opening_accept_needs_the_continue_limit_but_not_the_wait_limits(
        tmp_path, monkeypatch, clock):
    blades = foundation.route_silver_blades
    old = tuple((name, action, waiting_for, 3 if name == "continue" else limit)
                for name, action, waiting_for, limit in blades.PUBLISHED_INTERSTITIALS)
    base = blades.published_title("A", items_screen=False, opening_scene=True)
    folder = tmp_path / "0"
    folder.mkdir()
    _, result, _ = _opening_accept(folder, monkeypatch, clock,
                                   title=dataclasses.replace(base, interstitials=old))
    assert result["success"] is False
    assert "treasure_bar screen was not recognized" in result["error"]
    # The wait clock restarts after each interstitial, so the default limit now covers the
    # twelve continue presses that the per-state limits were added for.
    folder = tmp_path / "1"
    folder.mkdir()
    _, result, _ = _opening_accept(folder, monkeypatch, clock,
                                   title=dataclasses.replace(base, wait_limits={}))
    assert result["error"] == "" and result["success"] is True


def test_a_strict_world_stops_on_an_unguarded_screen_instead_of_settling(
        tmp_path, monkeypatch, clock):
    guest = OpeningGuest(clock, unguarded_world=True)
    _, result, _ = _opening_accept(tmp_path, monkeypatch, clock, guest=guest)
    assert result["success"] is False
    assert "world screen was not recognized" in result["error"]
    assert "NP8" not in _keys(guest)


def test_a_wait_limit_must_be_positive():
    blades = foundation.route_silver_blades
    with pytest.raises(winuaesession.RouteError, match="wait limit"):
        dataclasses.replace(blades.published_title("A"), wait_limits={"world": 0})


def test_the_walk_verdict_accepts_three_three_to_three_five_facing_south():
    before = dict(SSB_START)
    control = {"place": before}
    after = {"place": {"area": 16, "x": 3, "y": 5, "facing": geo.SOUTH}}
    verdict = foundation.walk_verdict(before, control, after, 2, turn=None)
    assert verdict["b_ok"] and verdict["d_ok"]
    blocked = foundation.walk_verdict(before, control, {"place": before}, 2, turn=None)
    assert blocked["walk_blocked"] and not blocked["d_ok"]


def test_the_start_map_lets_the_party_walk_south_twice_and_not_north_or_east():
    from tests.secret_of_the_silver_blades import test_ssblive  # noqa: PLC0415

    start = test_ssblive._first_map()  # skips without the Silver Blades disks
    assert start.is_passable(3, 3, geo.SOUTH)
    assert start.is_passable(3, 4, geo.SOUTH)
    assert start.door(3, 4, geo.SOUTH) == geo.PASSABLE
    assert not start.is_passable(3, 3, geo.EAST)
    assert not start.is_passable(3, 3, geo.NORTH)


def test_the_real_silver_blades_c64_pins_include_the_share_one_specimen():
    pins = foundation._source_pins(foundation.PUBLISHED_ISSUE, "ssb", "c64")
    assert "bacfa0d95954aacaabfe61d871ef39d989d70a11f9b125ca6a2d51ee41519240" in pins
    assert "0" * 64 not in pins
    assert foundation._source_pins(foundation.PUBLISHED_ISSUE, "curse", "c64") <= (
        foundation.PUBLISHED_SOURCES[("curse", "c64")])


CURSE_C64_SHARE_ONE = "8fefc9d73136b0db87e4996e5cc24855a4cb32e1c4db15a668814363d4bdb076"
CURSE_WALLED_WEST = {"area": 1, "x": 5, "y": 13, "facing": geo.WEST}


def test_the_real_curse_c64_pins_include_the_share_one_specimen():
    pins = foundation._source_pins(foundation.PUBLISHED_ISSUE, "curse", "c64")
    assert CURSE_C64_SHARE_ONE in pins
    assert "fdf74e5ff41fe0f90f8f9b150d966df276c4dc4e5ecd6829efee2fee9019acc1" in pins


def test_a_curse_party_facing_the_wall_west_of_five_thirteen_is_turned_about(tmp_path, monkeypatch):
    report, _ = _published_report(tmp_path, monkeypatch, name="curse", issue="640",
                                  place=CURSE_WALLED_WEST)
    path = foundation.prepare_published("curse", "runwall", report, "640")
    assert json.loads(path.read_text())["turn_about"] is True
    _, title = foundation._published_manifest(path, "curse")
    assert title.turn == "about"


@pytest.mark.parametrize("place", [
    {"area": 1, "x": 5, "y": 13, "facing": geo.EAST},
    {"area": 1, "x": 4, "y": 13, "facing": geo.WEST},
])
def test_only_the_walled_square_turns_a_curse_party_about(tmp_path, monkeypatch, place):
    report, _ = _published_report(tmp_path, monkeypatch, name="curse", issue="640", place=place)
    path = foundation.prepare_published("curse", "runother", report, "640")
    assert json.loads(path.read_text())["turn_about"] is False


def test_a_silver_blades_dos_party_on_the_start_square_walks_south_unturned():
    start = {"area": 16, "x": 3, "y": 3, "facing": geo.SOUTH}
    assert foundation._turn_about("ssb", "D", start) is False
    title = foundation._published_title("ssb", "D", turn_about=False)
    assert title.turn is None
    assert ("NP2", "world", "turn") not in [step[:3] for step in title.route]


@pytest.mark.parametrize("place", [
    {"area": 16, "x": 3, "y": 7, "facing": geo.SOUTH},
    {"area": 16, "x": 3, "y": 14, "facing": geo.SOUTH},
    {"area": 16, "x": 3, "y": 3, "facing": geo.NORTH},
])
def test_a_silver_blades_dos_party_elsewhere_still_turns_about(place):
    assert foundation._turn_about("ssb", "D", place) is True


def test_the_curse_start_map_has_a_wall_west_of_five_thirteen_and_east_of_seven():
    where = gamedata.curse_dir()
    if where is None:
        pytest.skip("no Curse of the Azure Bonds disks")
    start = None
    for side in sorted(where.glob("CURSE*.[dD]64")):
        start = geo.load_geo_files(str(side)).get("GEO01")
        if start is not None:
            break
    if start is None:
        pytest.skip("no Curse disk side carries GEO01")
    assert not start.is_passable(5, 13, geo.WEST)
    assert not start.is_passable(7, 13, geo.EAST)
    assert start.is_passable(5, 13, geo.EAST)
    assert start.is_passable(6, 13, geo.EAST)


def test_a_source_in_the_pin_set_is_accepted_and_an_unlisted_one_is_blocked(tmp_path, monkeypatch):
    path = _prepared_published(tmp_path, monkeypatch)
    manifest = json.loads(path.read_text())
    pinned = manifest["source_sha256"]
    other = "bacfa0d95954aacaabfe61d871ef39d989d70a11f9b125ca6a2d51ee41519240"
    monkeypatch.setitem(foundation.PUBLISHED_SOURCES, ("ssb", "c64"), frozenset({other, pinned}))
    foundation._published_manifest(path, "ssb")
    monkeypatch.setitem(foundation.PUBLISHED_SOURCES, ("ssb", "c64"), frozenset({other}))
    with pytest.raises(winuaesession.RouteError, match="differs from the pinned specimen"):
        foundation._published_manifest(path, "ssb")


def test_the_pool_walk_east_off_the_slums_is_judged_moved_into_new_phlan(tmp_path, clock):
    start = {"area": 20, "x": 15, "y": 4, "facing": geo.WEST}
    land = {"area": 0, "x": 0, "y": 4, "facing": geo.EAST}
    guest = TitleGuest(clock, save_key="save", land=land)
    _, result = _run(tmp_path, clock, guest=guest, start=start, expected_after=None)
    assert result["error"] == "", result["read"]
    assert result["walk"]["d_ok"] is True and result["success"] is True
    assert result["walk"]["area_crossed"] == {"from": 20, "to": 0}


# A Pools of Darkness run on a disk 3 that Wish wrote, with the registered disks replaced by
# synthetic ones whose slots are JSON, so the checks run without the player's disks.
THREE_SOURCE = b"a DOS slot"
THREE_START = dict(DARK_START, x=3)


def _pty(place, names=NAMES):
    return json.dumps({"place": place, "names": names}).encode()


def _pty_read(disk, letter):
    try:
        raw = disk.read_file(f"/SAVE/SavGam{letter}.pty")
    except Exception:
        return {"missing": True, "sha256": None}
    data = json.loads(raw)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "place": data["place"],
            "names": data["names"]}


def _pty_letters(disk):
    return sorted(e.name[6].upper() for e in disk.entries(disk.lookup("/SAVE").block)
                  if e.name.lower().startswith("savgam") and e.name.lower().endswith(".pty"))


def _pty_files(disk, letter):
    name = f"SavGam{letter}.pty"
    return {name: disk.read_file(f"/SAVE/{name}")}


#: The shipped vault: empty, with the item table padding that Wish's own empty vault lacks.
_STUB_VAULT = bytearray(amiga_savegame.pod_vault_to_amiga(dos_codec.EMPTY_POD_VAULT))
_STUB_VAULT[-1] = 0x55
_STUB_VAULT = bytes(_STUB_VAULT)
#: What Wish writes for a converted slot's empty vault.
LOADED_VAULT = amiga_savegame.pod_vault_to_amiga(dos_codec.EMPTY_POD_VAULT)


def _registered_three():
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir("/SAVE")
    disk.write_file("/SAVE/write.me", b"x")
    disk.write_file("/SAVE/spindisk", b"y")
    for letter in "ABCDE":
        disk.write_file(f"/SAVE/SavGam{letter}.pty", _pty(dict(DARK_START, x=5), ["OLD"]))
    # Every shipped disk 3 holds a vault for A to H and T, whether or not a saved game goes with it.
    for letter in "ABCDEFGHT":
        disk.write_file(f"/SAVE/Vault{letter}.DAT", _STUB_VAULT)
    return disk


class Three:
    """A registered disk 3, and the Save As report and image that publish a DOS slot onto it."""

    def __init__(self, tmp_path, monkeypatch, *, pin=True):
        self.tmp = tmp_path
        monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath("cache", *parts))
        self.registered = _registered_three()
        self.registered_path = tmp_path / "registered3.adf"
        self.registered.save(self.registered_path)
        self.ones = {key: AmigaDisk.blank(label).to_bytes()
                     for key, label in (("disk1", "POD 1"), ("disk2", "POD 2"))}
        sha = {k: hashlib.sha256(v).hexdigest() for k, v in self.ones.items()}
        monkeypatch.setattr(foundation, "DARKNESS_DISK1_SHA256", sha["disk1"])
        monkeypatch.setattr(foundation, "DARKNESS_DISK2_SHA256", sha["disk2"])
        monkeypatch.setattr(foundation, "DARKNESS_DISK3_SHA256",
                            hashlib.sha256(self.registered_path.read_bytes()).hexdigest())
        monkeypatch.setattr(foundation, "_find_images", lambda wanted: {
            key: (key, self.ones[key]) for key in wanted})
        dark = dataclasses.replace(foundation.DARKNESS, read_slot=_pty_read,
                                   slot_letters=_pty_letters, slot_files=_pty_files)
        monkeypatch.setattr(foundation, "DARKNESS", dark)
        monkeypatch.setattr(route_darkness, "DARKNESS", dark)
        self.source = tmp_path / "SAVGAMD.PTY"
        self.source.write_bytes(THREE_SOURCE)
        self.source_sha = hashlib.sha256(THREE_SOURCE).hexdigest()
        monkeypatch.setattr(foundation, "PUBLISHED_SOURCES_BY_ISSUE", {
            **foundation.PUBLISHED_SOURCES_BY_ISSUE,
            **({"2": {("darkness", "dos"): frozenset({self.source_sha})}} if pin else {})})

    def published(self, letter="D", *, mutate=None):
        disk = AmigaDisk(self.registered.to_bytes())
        disk.write_file(f"/SAVE/SavGam{letter}.pty", _pty(THREE_START))
        disk.write_file(f"/SAVE/Vault{letter}.DAT", LOADED_VAULT)
        if mutate:
            mutate(disk)
        return disk

    def report(self, disk, letter="D", name="darkness-three.adf", **over):
        image = self.tmp / name
        disk.save(image)
        sha = hashlib.sha256(image.read_bytes()).hexdigest()
        report = {"specimen": str(self.source), "specimen_sha256": self.source_sha,
                  "amiga_disk3": str(self.registered_path), "written": [str(image)],
                  "written_sha256": {image.name: sha},
                  "save_as": {"to": "amiga", "slot": letter, "source": str(self.source),
                              "written": [str(image)], "destination": str(image),
                              "stopped": False, "losses": [], "dropped": []}}
        report.update(over)
        path = self.tmp / f"report-{name}.json"
        path.write_text(json.dumps(report))
        return path, image


def _three_manifest(path):
    return json.loads(path.read_text())


def test_a_published_disk_3_prepare_replaces_a_held_letter_and_takes_the_next_free_two(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, image = three.report(three.published("D"))
    path = foundation.prepare_published_disk_three("run", report, "WISH-2")
    manifest = _three_manifest(path)
    assert path.parent == tmp_path / "cache" / "acceptance" / "WISH-2" / "run"
    assert manifest["mode"] == foundation.PUBLISHED_DISK_THREE_MODE
    assert manifest["loaded_letter"] == "D" and manifest["state_a"] == THREE_START
    assert (manifest["control_letter"], manifest["after_letter"]) == ("F", "G")
    assert manifest["kept_letters"] == ["A", "B", "C", "E"]
    assert manifest["disks"]["disk3"]["sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
    assert manifest["source_sha256"] == three.source_sha
    title = foundation.published_darkness_title(path, "darkness")
    assert ("D", "disk2_prompt", "key") in title.route and ("B", "disk2_prompt", "key") not in title.route
    assert [s[0] for s in title.route if s[2] == "write"] == ["F", "G"]
    assert title.plain_keys == (("E", "loaded_menu"), ("B", "journal"), ("E", "camp"))


def test_a_published_disk_3_prepare_for_a_letter_the_disk_lacks_adds_it_and_saves_past_it(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("F"), letter="F")
    manifest = _three_manifest(foundation.prepare_published_disk_three("run", report, "2"))
    assert manifest["loaded_letter"] == "F"
    assert (manifest["control_letter"], manifest["after_letter"]) == ("G", "H")
    assert manifest["kept_letters"] == ["A", "B", "C", "D", "E"]


@pytest.mark.parametrize("why, build, issue", [
    ("a file outside the slot changed",
     lambda three: three.published("D", mutate=lambda d: d.write_file("/SAVE/write.me", b"z")),
     "2"),
    ("a file was added outside the slot",
     lambda three: three.published("D", mutate=lambda d: d.write_file("/SAVE/extra", b"z")),
     "2"),
    ("the slot was not converted", lambda three: three.published_unchanged(), "2"),
    ("no source is pinned for the ticket", lambda three: three.published("D"), "3"),
])
def test_a_published_disk_3_prepare_blocks_and_leaves_no_run_folder(
        tmp_path, monkeypatch, why, build, issue):
    three = Three(tmp_path, monkeypatch)
    three.published_unchanged = lambda: AmigaDisk(three.registered.to_bytes())
    report, _ = three.report(build(three))
    with pytest.raises(winuaesession.RouteError):
        foundation.prepare_published_disk_three("run", report, issue)
    assert not (tmp_path / "cache").exists(), why


def test_a_published_disk_3_prepare_blocks_a_source_and_a_report_that_disagree(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    disk = three.published("D")
    wrong = three.report(disk, specimen_sha256="0" * 64)[0]
    with pytest.raises(winuaesession.RouteError, match="source differs"):
        foundation.prepare_published_disk_three("run", wrong, "2")
    lossy = three.report(disk, name="lossy.adf")[0]
    data = json.loads(lossy.read_text())
    data["save_as"]["losses"] = ["a field"]
    lossy.write_text(json.dumps(data))
    with pytest.raises(winuaesession.RouteError, match="lossless"):
        foundation.prepare_published_disk_three("run", lossy, "2")
    other = three.report(disk, name="other.adf", amiga_disk3=str(three.source))[0]
    with pytest.raises(winuaesession.RouteError, match="registered pin"):
        foundation.prepare_published_disk_three("run", other, "2")
    assert not (tmp_path / "cache").exists()


def test_a_published_disk_3_prepare_blocks_a_slot_whose_vault_is_not_the_converted_vault(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    # The shipped stub where the converted vault belongs.
    report, _ = three.report(three.published("D", mutate=lambda disk: disk.write_file(
        "/SAVE/VaultD.DAT", _STUB_VAULT)))
    with pytest.raises(winuaesession.RouteError, match="not the vault converted"):
        foundation.prepare_published_disk_three("run", report, "2")
    assert not (tmp_path / "cache").exists()


def test_a_published_disk_3_prepare_removes_its_folder_when_a_working_copy_differs(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    monkeypatch.setattr(foundation.shutil, "copyfile",
                        lambda src, dst: pathlib.Path(dst).write_bytes(b"other"))
    with pytest.raises(winuaesession.RouteError, match="working copy differs"):
        foundation.prepare_published_disk_three("run", report, "2")
    assert not list((tmp_path / "cache").rglob("run"))


def test_a_failed_published_disk_3_prepare_removes_its_read_only_copies(tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    real_unlink = os.unlink

    def windows_unlink(path, *args, **kwargs):
        if not os.access(path, os.W_OK):
            raise PermissionError(13, "Access is denied", str(path))
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(foundation.os, "unlink", windows_unlink)
    monkeypatch.setattr(foundation.os, "remove", windows_unlink)
    monkeypatch.setattr(foundation.shutil, "copyfile",
                        lambda src, dst: pathlib.Path(dst).write_bytes(b"other"))
    with pytest.raises(winuaesession.RouteError, match="working copy differs"):
        foundation.prepare_published_disk_three("run", report, "2")
    assert not list((tmp_path / "cache").rglob("run"))


def test_a_published_disk_3_prepare_removes_its_folder_when_a_registered_image_changed(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    calls = []

    def find(wanted):
        calls.append(1)
        return {key: (key, three.ones[key] if len(calls) < 2 else b"changed") for key in wanted}

    monkeypatch.setattr(foundation, "_find_images", find)
    with pytest.raises(winuaesession.RouteError, match="registered image changed"):
        foundation.prepare_published_disk_three("run", report, "2")
    assert not list((tmp_path / "cache").rglob("run"))


def test_a_published_disk_3_prepare_files_number_and_wish_number_under_one_folder(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    path = foundation.prepare_published_disk_three("run", report, "2")
    assert path.parent == tmp_path / "cache" / "acceptance" / "WISH-2" / "run"
    assert _three_manifest(path)["issue"] == "WISH-2"
    with pytest.raises(winuaesession.RouteError, match="already exists"):
        foundation.prepare_published_disk_three("run", report, "WISH-2")


def test_published_letters_take_the_first_two_letters_without_a_saved_game():
    # A letter that only a vault holds is the shipped state; the game overwrites that vault when it saves.
    assert route_darkness.published_letters("D", ["A", "B", "C", "D", "E"]) == (
        "F", "G", ("A", "B", "C", "E"))
    with pytest.raises(winuaesession.RouteError, match="free to save to"):
        route_darkness.published_letters("D", ["A", "B", "C", "D", "E", "F", "G"])


def test_a_published_disk_3_prepare_keeps_camp_steps_and_blocks_bad_ones_before_a_folder_exists(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    with pytest.raises(winuaesession.RouteError):
        foundation.prepare_published_disk_three("run", report, "2", camp=("view 9",))
    assert not (tmp_path / "cache").exists()
    path = foundation.prepare_published_disk_three(
        "run", report, "2", camp=("view", "rest 1h", "snapshot s", "restore s"))
    manifest = _three_manifest(path)
    assert manifest["camp"] == list(foundation.route_camp.normalise(
        ("view", "rest 1h", "snapshot s", "restore s")))
    title = foundation.accept_title(foundation.published_darkness_title(path, "darkness"), manifest)
    assert title.route.index(("S", "camp_save_picker", "key")) > title.route.index(("E", "camp", "key"))
    marks = foundation.route_camp.camp_marks(
        title, tuple(manifest["camp"]), len(manifest["names_a"]), name="darkness")
    assert any(("snapshot", "s") in pairs for pairs in marks.values())


def test_a_published_disk_3_manifest_is_blocked_when_its_disk_or_pin_changed(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    path = foundation.prepare_published_disk_three("run", report, "2")
    manifest = _three_manifest(path)
    for change, match in (({"control_letter": "H"}, "save letters"),
                          ({"source_sha256": "0" * 64}, "pinned specimen"),
                          ({"title": "pool"}, "CLI title")):
        path.write_text(json.dumps({**manifest, **change}))
        with pytest.raises(winuaesession.RouteError, match=match):
            foundation.published_darkness_title(path, "darkness")
    path.write_text(json.dumps(manifest))
    assert foundation.published_darkness_title(path, "darkness") is not None
    assert foundation.published_darkness_title(_dark_manifest(tmp_path), "darkness") is None


def test_run_recon_blocks_a_title_that_is_not_the_published_disk_3_route(tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    path = foundation.prepare_published_disk_three("run", report, "2")
    with pytest.raises(winuaesession.RouteError, match="differs from the published disk 3"):
        foundation.run_recon(path, guest=winuaesession.WinGuest(), guard=MapGuard(states=DARK_STATES, on={}),
                             identity=_IdentityMap(), holder="wish2-test",
                             audio_proof=_audio_proof(tmp_path), title=route_darkness.DARKNESS,
                             accept=True)


def _accepted(three, path, tmp_path, *, same_place=False, extra=None, vaults=None):
    """A fetched disk 3 as an accept run leaves it: the control and after saves added.

    The game copies the loaded slot's vault into both new letters; `vaults` maps a letter to other bytes.
    """
    manifest = _three_manifest(path)
    published = AmigaDisk.open(manifest["registered"]["published"]["path"])
    fetched = AmigaDisk(published.to_bytes())
    fetched.write_file(f"/SAVE/SavGam{manifest['control_letter']}.pty", _pty(THREE_START))
    fetched.write_file(f"/SAVE/SavGam{manifest['after_letter']}.pty",
                       _pty(THREE_START if same_place else dict(THREE_START, x=4)))
    loaded = published.read_file(f"/SAVE/Vault{manifest['loaded_letter']}.DAT")
    for letter in (manifest["control_letter"], manifest["after_letter"]):
        fetched.write_file(f"/SAVE/Vault{letter}.DAT", (vaults or {}).get(letter, loaded))
    if extra:
        fetched.write_file(*extra)
    file = tmp_path / "fetched3.adf"
    fetched.save(file)
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"success": True, "accept": True,
                                   "fetched": {"disk3": {"sha256": sha}}}))
    return file, sha, summary


def test_a_published_disk_3_reload_loads_the_after_slot_and_keeps_every_other(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    path = foundation.prepare_published_disk_three("run", report, "WISH-2")
    file, sha, summary = _accepted(three, path, tmp_path)
    reload = foundation.prepare_published_disk_three_reload("again", path, file, sha, summary)
    manifest = _three_manifest(reload)
    assert reload.parent == tmp_path / "cache" / "acceptance" / "WISH-2" / "again"
    assert manifest["mode"] == foundation.PUBLISHED_DISK_THREE_RELOAD_MODE
    assert manifest["loaded_letter"] == "G" and manifest["other_letter"] == "F"
    assert manifest["state_a"] == dict(THREE_START, x=4) and manifest["other_place"] == THREE_START
    assert manifest["kept_letters"] == ["A", "B", "C", "D", "E", "F"]
    assert manifest["vault_sha256"] == {c: hashlib.sha256(LOADED_VAULT).hexdigest() for c in "FG"}
    title = foundation.published_darkness_title(reload, "darkness-reload")
    assert title.control_letter is None and title.kept_letters == tuple("ABCDEF")
    assert ("G", "disk2_prompt", "key") in title.route
    assert title.plain_keys == (("E", "loaded_menu"), ("B", "journal"))


@pytest.mark.parametrize("squares, expected", [
    ({"G": (22, 5), "F": (22, 4)}, {"wilderness_a": (22, 5), "wilderness_other": (22, 4)}),
    ({}, {}),
])
def test_a_published_disk_3_reload_records_the_wilderness_squares_of_overland_slots(
        tmp_path, monkeypatch, squares, expected):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    path = foundation.prepare_published_disk_three("run", report, "WISH-2")
    file, sha, summary = _accepted(three, path, tmp_path)
    plain = foundation.DARKNESS.read_slot

    def read(disk, letter):
        one = plain(disk, letter)
        if letter in squares:
            one = dict(one, in_dungeon=False, wilderness_square=list(squares[letter]))
        return one

    monkeypatch.setattr(foundation, "DARKNESS",
                        dataclasses.replace(foundation.DARKNESS, read_slot=read))
    manifest = _three_manifest(
        foundation.prepare_published_disk_three_reload("again", path, file, sha, summary))
    for key in ("wilderness_a", "wilderness_other"):
        want = expected.get(key)
        assert manifest.get(key) == (list(want) if want else None)


@pytest.mark.parametrize("why, kwargs, match", [
    ("same place", {"same_place": True}, "one place"),
    ("an extra file", {"extra": ("/SAVE/VaultI.DAT", b"v")}, "plus slots"),
])
def test_a_published_disk_3_reload_blocks_a_disk_that_is_not_the_published_one_plus_two_saves(
        tmp_path, monkeypatch, why, kwargs, match):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    path = foundation.prepare_published_disk_three("run", report, "2")
    file, sha, summary = _accepted(three, path, tmp_path, **kwargs)
    with pytest.raises(winuaesession.RouteError, match=match):
        foundation.prepare_published_disk_three_reload("again", path, file, sha, summary)
    assert not (tmp_path / "cache" / "acceptance" / "2" / "again").exists(), why


@pytest.mark.parametrize("letter", ["F", "G"])
def test_a_published_disk_3_reload_blocks_a_new_slot_whose_vault_is_not_the_loaded_one(
        tmp_path, monkeypatch, letter):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    path = foundation.prepare_published_disk_three("run", report, "2")
    other = amiga_savegame.pod_vault_to_amiga(dos_codec.PodVault(7, 0, 0, ()))
    file, sha, summary = _accepted(three, path, tmp_path, vaults={letter: other})
    with pytest.raises(winuaesession.RouteError, match="is not the loaded slot's vault"):
        foundation.prepare_published_disk_three_reload("again", path, file, sha, summary)
    assert not (tmp_path / "cache" / "acceptance" / "WISH-2" / "again").exists()


def test_a_published_disk_3_reload_blocks_a_summary_of_another_disk_or_a_failed_run(
        tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    report, _ = three.report(three.published("D"))
    path = foundation.prepare_published_disk_three("run", report, "2")
    file, sha, summary = _accepted(three, path, tmp_path)
    data = json.loads(summary.read_text())
    summary.write_text(json.dumps({**data, "success": False}))
    with pytest.raises(winuaesession.RouteError, match="not a successful accept"):
        foundation.prepare_published_disk_three_reload("again", path, file, sha, summary)
    summary.write_text(json.dumps({**data, "fetched": {"disk3": {"sha256": "0" * 64}}}))
    with pytest.raises(winuaesession.RouteError, match="another disk"):
        foundation.prepare_published_disk_three_reload("again", path, file, sha, summary)


@pytest.mark.parametrize("issue, ok", [("WISH-2", True), ("2", True), ("WISH-", False),
                                       ("wish-2", False), ("2x", False), ("../2", False)])
def test_prepare_takes_a_number_or_wish_n_for_the_run_folder(tmp_path, monkeypatch, issue, ok):
    monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))

    def fake(run, specimen, **substitute):  # darkness takes `substitute` keywords now
        scratch.ensure(run)
        return {"title": "darkness", "names_a": NAMES}

    monkeypatch.setattr(foundation, "_PREPARE", {"darkness": fake})
    if ok:
        path = foundation.prepare(foundation.DARKNESS, "run", issue=issue)
        assert path.parent == tmp_path / "acceptance" / issue / "run"
    else:
        with pytest.raises(winuaesession.RouteError, match="WISH-N"):
            foundation.prepare(foundation.DARKNESS, "run", issue=issue)


def test_the_cli_routes_a_published_disk_3_prepare_and_its_reload(tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(foundation, "prepare_published_disk_three",
                        lambda *a, **k: seen.append(("three", a, k)) or tmp_path / "p.json")
    monkeypatch.setattr(foundation, "prepare_published_disk_three_reload",
                        lambda *a, **k: seen.append(("reload", a, k)) or tmp_path / "r.json")
    head = ["prepare", "--published-disk-three", "--run-id", "r", "--issue", "WISH-2"]
    assert foundation.main([*head, "--title", "darkness", "--saveas-report", "rep.json",
                            "--camp", "view"]) == 0
    assert seen[0][0] == "three" and seen[0][1][:3] == ("r", pathlib.Path("rep.json"), "WISH-2")
    assert seen[0][2] == {"camp": ("view 1",)}
    assert foundation.main([*head, "--title", "darkness-reload", "--published-manifest", "m.json",
                            "--disk3", "d.adf", "--disk3-sha256", "ab",
                            "--accept-summary", "s.json"]) == 0
    assert seen[1][1] == ("r", pathlib.Path("m.json"), pathlib.Path("d.adf"), "ab",
                          pathlib.Path("s.json"), "WISH-2")
    for argv in ([*head, "--title", "darkness"], [*head, "--title", "pool", "--saveas-report", "x"],
                 [*head, "--title", "darkness-reload"],
                 [*head, "--title", "darkness", "--saveas-report", "x", "--published-disk-one"],
                 ["prepare", "--run-id", "r", "--title", "darkness", "--published-manifest", "m"]):
        assert foundation.main(argv) == 2
    assert len(seen) == 2


_VAULT_LEAD = (
    ("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
    ("B", "disk2_prompt", "key"), route_darkness.DISK2_INSERT,
    ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
    ("S", "save_picker", "key"), ("F", "loaded_menu", "write"),
    ("B", "journal", "key"), ("X", "journal_answer", "key"),
    ("RET", "elminster_menu", "key"))
_VAULT_TAIL = (("R", "camp", "key"), ("S", "camp_save_picker", "key"),
               ("G", "exit_game", "write"), ("N", "camp", "key"))


def test_the_darkness_vault_description_is_pinned():
    vault = foundation.DARKNESS_VAULT
    assert foundation.TITLES["darkness-vault"] is vault
    assert route_darkness.vault_title() == vault
    assert route_darkness.vault_title(40, True) == vault
    assert vault.route == (
        *_VAULT_LEAD,
        ("S", "vault_bar", "key"), ("T", "vault_take", "key"), ("I", "vault_items", "key"),
        *[("NP2", "vault_row", "key")] * 39,
        ("E", "vault_take", "key"), ("E", "vault_bar", "key"), ("E", "elminster_menu", "key"),
        *_VAULT_TAIL)
    assert vault.measure_route == (*vault.route[:7], *vault.route[9:len(vault.route) - 2])
    assert vault.control_letter == "F" and vault.after_letter == "G"
    assert vault.plain_keys == (
        ("E", "loaded_menu"), ("E", "vault_take"), ("E", "vault_bar"), ("E", "elminster_menu"))
    assert {"elminster_menu", "camp"} <= vault.strict
    assert "world" not in vault.strict
    # The guards for these states are cut from an empty vault or not cut at all.
    assert not vault.strict & {"vault_bar", "vault_take", "vault_items", "vault_row"}
    assert vault.min_waits["vault_row"] == route_camp.ROW_WAIT


@pytest.mark.parametrize("items", [1, 2, 40, 200])
def test_the_vault_steps_without_coins_go_from_t_straight_to_the_list(items):
    steps = route_darkness.vault_steps(items, False)
    assert steps == (
        ("S", "vault_bar", "key"), ("T", "vault_items", "key"),
        *[("NP2", "vault_row", "key")] * (items - 1),
        ("E", "vault_bar", "key"), ("E", "elminster_menu", "key"))
    assert "N" not in {s[0] for s in steps}


@pytest.mark.parametrize("items", [1, 2, 40, 200])
def test_the_vault_steps_with_coins_open_take_then_the_list(items):
    steps = route_darkness.vault_steps(items, True)
    assert steps == (
        ("S", "vault_bar", "key"), ("T", "vault_take", "key"), ("I", "vault_items", "key"),
        *[("NP2", "vault_row", "key")] * (items - 1),
        ("E", "vault_take", "key"), ("E", "vault_bar", "key"), ("E", "elminster_menu", "key"))
    assert "N" not in {s[0] for s in steps}


def test_a_vault_of_none_or_more_than_the_game_holds_builds_no_route():
    for items in (0, 449):
        for coins in (False, True):
            with pytest.raises(foundation.RouteError, match="1 to 448 items"):
                route_darkness.vault_steps(items, coins)
            with pytest.raises(foundation.RouteError, match="1 to 448 items"):
                route_darkness.vault_title(items, coins)


def test_a_vault_run_of_two_hundred_items_builds_a_title():
    title = route_darkness.vault_title(200, False)
    assert [s for s in title.route if s[1] == "vault_row"] == [("NP2", "vault_row", "key")] * 199
    assert title.route[-4:] == _VAULT_TAIL
    assert title.min_waits["vault_row"] == route_camp.ROW_WAIT
    assert ("E", "vault_take") not in title.plain_keys


def test_the_vault_title_answers_no_interstitial_row_because_it_never_expects_the_world():
    assert foundation.DARKNESS_VAULT.interstitials == ()
    assert route_darkness.vault_title(200, False).interstitials == ()


_HELD = {"items": 40, "coins": [1750, 495, 82], "sha256": "ab"}


def _prepare_with(monkeypatch, tmp_path, seen, held=_HELD):
    monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))

    def fake(run, specimen, **kw):
        seen.append(kw)
        scratch.ensure(run)
        return {"title": "darkness", "names_a": NAMES}

    def fake_vault(run, specimen, **kw):
        return {**fake(run, specimen, **kw), "vault": held}

    monkeypatch.setattr(foundation, "_PREPARE",
                        {"darkness-vault": fake_vault, "darkness": fake})


def test_the_vault_prepare_runs_the_darkness_prepare_with_its_vault_switch_on():
    prepare = foundation._PREPARE["darkness-vault"]
    assert prepare.func is foundation._prepare_darkness
    assert prepare.keywords == {"vault": True}
    assert foundation._PREPARE["darkness"] is foundation._prepare_darkness


def test_a_vault_prepare_takes_a_substitute_and_keeps_the_vault_its_prepare_recorded(
        tmp_path, monkeypatch):
    seen = []
    _prepare_with(monkeypatch, tmp_path, seen)
    substitute = tmp_path / "converted.adf"
    path = foundation.prepare(foundation.DARKNESS_VAULT, "run", substitute=substitute,
                              substitute_letter="B")
    assert seen == [{"substitute": substitute, "substitute_letter": "B"}]
    assert json.loads(path.read_text())["vault"] == _HELD
    plain = json.loads(foundation.prepare(foundation.DARKNESS, "run2").read_text())
    assert "vault" not in plain


def test_a_vault_prepare_blocks_a_vault_the_route_cannot_list_and_frees_its_run_id(
        tmp_path, monkeypatch):
    _prepare_with(monkeypatch, tmp_path, [], held={**_HELD, "items": 449})
    with pytest.raises(winuaesession.RouteError, match="1 to 448 items"):
        foundation.prepare(foundation.DARKNESS_VAULT, "run")
    assert not (tmp_path / "acceptance" / foundation.ISSUE / "run").exists()


def test_the_cli_dispatches_a_vault_prepare_with_its_substitute_and_has_no_page_count(
        tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(foundation, "prepare",
                        lambda title, run_id, **kw: seen.append((title, run_id, kw))
                        or tmp_path / "p.json")
    assert foundation.main(["prepare", "--title", "darkness-vault", "--run-id", "r",
                            "--substitute", "s.adf", "--substitute-letter", "B"]) == 0
    title, run_id, kw = seen[0]
    assert title is foundation.DARKNESS_VAULT and run_id == "r"
    assert kw["substitute"] == pathlib.Path("s.adf") and kw["substitute_letter"] == "B"
    assert "vault_pages" not in kw
    with pytest.raises(SystemExit):
        foundation.main(["prepare", "--title", "darkness-vault", "--run-id", "r",
                         "--vault-pages", "13"])


@pytest.mark.parametrize("command", ["measure", "accept"])
def test_the_cli_runs_a_vault_title_at_the_rows_and_coins_its_manifest_recorded(
        tmp_path, monkeypatch, command):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda path: ("guards", str(path)))
    manifest = tmp_path / "prepare.json"
    expected = {}
    for held in ({"items": 200, "coins": [0, 0, 0]}, {"items": 40, "coins": [1750, 495, 82]}):
        manifest.write_text(json.dumps({"vault": held}))
        extra = ["--guards", "g.json"] + (
            ["--identity", "i.json"] if command == "accept" else [])
        assert foundation.main([command, "--title", "darkness-vault", "--manifest", str(manifest),
                                "--audio-proof", str(tmp_path / "mute.json"),
                                "--attempt", "a1", *extra]) == 0
        expected[held["items"]] = called.calls[-1]["title"]
    assert expected[200] == route_darkness.vault_title(200, False)
    assert expected[40] == foundation.DARKNESS_VAULT


def test_a_vault_manifest_without_a_vault_builds_no_title(tmp_path):
    manifest = tmp_path / "prepare.json"
    manifest.write_text("{}")
    with pytest.raises(winuaesession.RouteError, match="records no vault"):
        foundation._vault_title_for(manifest)


def _vault_disk(*vaults):
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir("/SAVE")
    for letter, vault in vaults:
        disk.write_file(f"/SAVE/Vault{letter}.DAT", amiga_savegame.pod_vault_to_amiga(vault))
    return disk


def test_the_vault_check_passes_saves_that_hold_the_staged_vault_and_names_one_that_does_not(
        tmp_path):
    staged = dos_codec.PodVault(1750, 495, 82, (bytes(63), bytes([1]) + bytes(62)))
    other = dos_codec.PodVault(1750, 495, 82, (bytes(63),))
    path = tmp_path / "staged.adf"
    _vault_disk(("B", staged)).save(path)
    fetched = _vault_disk(("F", staged), ("G", staged))
    assert foundation._vault_problems(fetched, path, "B", ("F", "G")) == []
    fetched = _vault_disk(("F", staged), ("G", other))
    assert foundation._vault_problems(fetched, path, "B", ("F", "G")) == [
        "vault G differs from the vault staged in slot B"]
    fetched = _vault_disk(("F", dos_codec.EMPTY_POD_VAULT), ("G", staged))
    assert foundation._vault_problems(fetched, path, "B", ("F", "G")) == [
        "vault F differs from the vault staged in slot B"]


#: The three game-written DOS saves that the Darkness Save As route starts from besides the
#: Lay on Hands slot, as `(specimen directory, SAVGAMD.PTY SHA-256)`.
DARKNESS_DOS_SOURCES = (
    ("pod-650-savgamb-walked-vault-dos",
     "416df285086ae434bbad4efcd2943bb419b94b287d2382fe9f5706bbb15ed371"),
    ("pod-650-savgama-join-weight-dos",
     "ed4a9f68f9e2f9064d229872bce0a2f87e017c8865123159f9af54a6d8a25bb8"),
    ("pod-stage3a-default-begin-walked-dos",
     "e913382f73be2ace0c95642d8a7742f5478ade09302f0abfe46f6259db30c11c"),
)


@pytest.mark.parametrize("name,sha", DARKNESS_DOS_SOURCES)
def test_the_darkness_save_as_route_pins_each_dos_source_of_its_ticket(name, sha):
    assert sha in foundation._source_pins("2", "darkness", "dos"), name


def test_the_darkness_save_as_route_pins_the_stage_5_dos_source():
    assert "ee979bf89164742816841c9ad2dc5a550f35b3a52eec2ad3fae138c9a1653918" in (
        foundation._source_pins("2", "darkness", "dos"))


def test_the_darkness_guards_hold_a_place_rule_for_the_square_after_stage_5s_walk():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    state = foundation.place_state(dict(area=2, x=3, y=2, facing=geo.EAST))
    assert state == "place_x3_y2_f1"
    rule = spec["guards"][state]
    assert rule["box"] == spec["guards"]["place_x2_y2_f1"]["box"]
    assert rule["also"] == spec["guards"]["place_x2_y2_f1"]["also"]
    example = rule["example"]
    assert spec["labels"][example] == [state]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the stage 5 accept shot 13 of WISH-2")
    assert screens.box_digests(crop, [tuple(rule["box"])], state)[tuple(rule["box"])] == rule["sha256"]


def test_the_darkness_guards_recognise_the_seven_member_loaded_menu_of_the_a2_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    example = "WISH-2/wish2-a2/measure1/shots/05-loaded_menu.png"
    assert spec["labels"][example] == ["loaded_menu"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the stage 8 A2 measure shot 05 of WISH-2")
    for kind, box in (("guards", [58, 262, 698, 432]), ("identity", [74, 94, 690, 192])):
        rules = [r for r in screens.rules_of(spec[kind]["loaded_menu"]) if r["example"] == example]
        assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == []
        assert screens.box_digests(crop, [tuple(box)], "loaded_menu")[tuple(box)] == rules[0]["sha256"]


def test_the_darkness_guards_recognise_the_first_member_sheet_of_the_a2_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    example = "WISH-2/wish2-a2/measure2/shots/06-sheet.png"
    assert spec["labels"][example] == ["sheet"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the stage 8 A2 measure shot 06 of WISH-2")
    camp = ["camp_sheet", "camp_sheet_heal", "camp_sheet_items", "camp_sheet_items_2", "camp_sheet_items_3",
            "camp_sheet_items_4", "camp_sheet_items_5", "camp_sheet_items_6", "camp_sheet_spent",
            *[f"camp_sheet_{n}" for n in range(2, 8)]]
    for kind, box, also in (("guards", [58, 402, 530, 430], sorted(camp)), ("identity", [74, 46, 330, 62], ["camp_sheet"])):
        rules = [r for r in screens.rules_of(spec[kind]["sheet"]) if r["example"] == example]
        assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == also
        assert screens.box_digests(crop, [tuple(box)], "sheet")[tuple(box)] == rules[0]["sha256"]


def test_every_darkness_camp_sheet_line_has_the_label_column_rule_of_line_1():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    first = spec["guards"]["camp_sheet"]
    for n in range(2, 8):
        rule = spec["guards"][f"camp_sheet_{n}"]
        assert (rule["box"], rule["sha256"]) == (first["box"], first["sha256"])
        crop = scratch.cache_dir("acceptance") / rule["example"]
        if crop.is_file():
            assert screens.box_digests(crop, [tuple(rule["box"])], f"camp_sheet_{n}")[tuple(rule["box"])] == rule["sha256"]
    example = "WISH-2/wish2-a2/measure2/shots/06-sheet.png"
    mine = [r for r in screens.rules_of(spec["identity"]["camp_sheet"]) if r["example"] == example]
    assert len(mine) == 1 and mine[0]["box"] == [74, 46, 330, 62] and mine[0]["also"] == ["sheet"]
    crop = scratch.cache_dir("acceptance") / example
    if crop.is_file():
        assert screens.box_digests(crop, [(74, 46, 330, 62)], "camp_sheet")[(74, 46, 330, 62)] == mine[0]["sha256"]


def test_the_darkness_guards_recognise_the_overland_world_bar_of_the_a3_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    example = "WISH-2/wish2-a3/measure-a3-7/shots/10-world.png"
    assert spec["labels"][example] == ["world", "place_x4_y7_f1_w22_5"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the stage 8 A3 measure shot 10 of WISH-2")
    box = [58, 402, 698, 430]
    rules = [r for r in screens.rules_of(spec["guards"]["world"]) if r["example"] == example]
    assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == ["place"]
    assert screens.box_digests(crop, [tuple(box)], "world")[tuple(box)] == rules[0]["sha256"]


def test_the_pool_identity_recognises_the_world_screen_of_the_eight_member_npc_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_pool.json").read_text())
    example = "300/wish300-amiga-npc/accept1/shots/04-world.png"
    assert spec["labels"][example] == ["world"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the WISH-300 Amiga NPC party run shot 04")
    box = [326, 96, 578, 194]
    rules = [r for r in screens.rules_of(spec["identity"]["world"]) if r["example"] == example]
    assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == ["camp", "camp_save_picker", "quit_prompt"]
    assert screens.box_digests(crop, [tuple(box)], "world")[tuple(box)] == rules[0]["sha256"]


def test_the_pool_identity_recognises_the_world_screen_of_the_six_member_wish301_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_pool.json").read_text())
    example = "301/wish301-amiga/accept2/shots/04-world.png"
    assert spec["labels"][example] == ["world"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the WISH-301 Amiga run shot 04")
    box = [326, 96, 578, 194]
    rules = [r for r in screens.rules_of(spec["identity"]["world"]) if r["example"] == example]
    assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == [
        "camp", "camp_save_picker", "encounter", "quit_prompt", "temple", "temple_greeting"]
    assert screens.box_digests(crop, [tuple(box)], "world")[tuple(box)] == rules[0]["sha256"]


def test_the_darkness_guards_recognise_the_journal_question_of_the_a2_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    example = "WISH-2/wish2-a2/measure3/shots/08-journal.png"
    assert spec["labels"][example] == ["journal"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the stage 8 A2 measure shot 08 of WISH-2")
    # The box leaves out the frame rows above and below the ENTER bar, which differ by boot.
    box = [74, 406, 170, 428]
    rules = [r for r in screens.rules_of(spec["guards"]["journal"]) if r["example"] == example]
    assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == ["journal_answer"]
    assert screens.box_digests(crop, [tuple(box)], "journal")[tuple(box)] == rules[0]["sha256"]


def test_the_pool_identity_recognises_the_first_sheet_of_the_eight_member_npc_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_pool.json").read_text())
    example = "300/wish300-amiga-npc2/accept1/shots/05-sheet.png"
    assert spec["labels"][example] == ["sheet"]
    shots = scratch.cache_dir("acceptance") / "300/wish300-amiga-npc2/accept1/shots"
    crop = shots / "failure.png"
    if not crop.is_file():
        pytest.skip("needs the WISH-300 Amiga NPC party run's sheet shot")
    box = [70, 66, 330, 80]
    rules = [r for r in screens.rules_of(spec["identity"]["sheet"]) if r["example"] == example]
    assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == []
    assert screens.box_digests(crop, [tuple(box)], "sheet")[tuple(box)] == rules[0]["sha256"]


def test_the_darkness_guards_recognise_the_camp_screen_of_the_a4_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    example = "WISH-2/wish2-a4/measure-a4-32/shots/12-camp.png"
    assert spec["labels"][example] == ["camp"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the stage 12 A4 measure shot 12 of WISH-2")
    # The box keeps the VIEW and MAGIC buttons; the buttons to their right depend on the party's hurt and spent state.
    box = [58, 402, 250, 430]
    rules = [r for r in screens.rules_of(spec["guards"]["camp"]) if r["example"] == example]
    assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == []
    assert screens.box_digests(crop, [tuple(box)], "camp")[tuple(box)] == rules[0]["sha256"]


def test_the_darkness_guards_recognise_the_journal_answer_inside_the_border_that_differs_between_boots():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    rule = spec["guards"]["journal_answer"]
    # The A2 boot's frame rows above and below the ENTER bar differ from the A3 boot's.
    assert rule["box"] == [74, 406, 200, 428]
    for example in ("WISH-2/wish2-a2/measure4/shots/09-journal_answer.png",
                    "WISH-2/wish2-a3/measure-a3-7/shots/09-journal_answer.png"):
        assert spec["labels"][example] == ["journal_answer"]
        crop = scratch.cache_dir("acceptance") / example
        if not crop.is_file():
            pytest.skip("needs the WISH-2 A2 measure4 and A3 measure-a3-7 shot 09")
        box = tuple(rule["box"])
        assert screens.box_digests(crop, [box], "journal_answer")[box] == rule["sha256"]


def test_the_darkness_identity_recognises_the_loaded_menu_and_first_sheet_of_the_a3_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    cases = (("loaded_menu", "WISH-2/wish2-a3/accept1/shots/05-loaded_menu.png", [74, 94, 690, 192]),
             ("sheet", "WISH-2/wish2-a3/measure-a3-8/shots/06-sheet.png", [74, 46, 330, 62]))
    root = scratch.cache_dir("acceptance")
    for state, example, box in cases:
        assert spec["labels"][example] == [state]
        crop = root / example
        if not crop.is_file():
            pytest.skip(f"needs the A3 shot {example} of WISH-2")
        rules = [r for r in screens.rules_of(spec["identity"][state]) if r["example"] == example]
        assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == (["camp_sheet"] if state == "sheet" else [])
        assert screens.box_digests(crop, [tuple(box)], state)[tuple(box)] == rules[0]["sha256"]
        # Another party's screen of the same state must not match this rule.
        others = [root / r["example"] for r in screens.rules_of(spec["identity"][state]) if r["example"] != example]
        for other in others:
            if other.is_file():
                assert screens.box_digests(other, [tuple(box)], state)[tuple(box)] != rules[0]["sha256"]


def test_the_darkness_guards_recognise_the_dungeon_world_bar_of_the_a2_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    example = "WISH-2/wish2-a2/measure5/shots/10-world.png"
    assert spec["labels"][example] == ["world", "place_x4_y10_f1"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the stage 8 A2 measure5 shot 10 of WISH-2")
    box = [58, 402, 698, 430]
    rules = [r for r in screens.rules_of(spec["guards"]["world"]) if r["example"] == example]
    assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == ["place"]
    assert screens.box_digests(crop, [tuple(box)], "world")[tuple(box)] == rules[0]["sha256"]


def test_the_darkness_identity_recognises_the_loaded_menu_and_first_sheet_of_the_a4_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    cases = (("loaded_menu", "WISH-2/wish2-a4/measure-a4-33/shots/05-loaded_menu.png", [74, 94, 690, 192]),
             ("sheet", "WISH-2/wish2-a4/measure-a4-33/shots/06-sheet.png", [74, 46, 330, 62]))
    root = scratch.cache_dir("acceptance")
    for state, example, box in cases:
        assert spec["labels"][example] == [state]
        crop = root / example
        if not crop.is_file():
            pytest.skip(f"needs the A4 shot {example} of WISH-2")
        rules = [r for r in screens.rules_of(spec["identity"][state]) if r["example"] == example]
        assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == (["camp_sheet"] if state == "sheet" else [])
        assert screens.box_digests(crop, [tuple(box)], state)[tuple(box)] == rules[0]["sha256"]
        others = [root / r["example"] for r in screens.rules_of(spec["identity"][state]) if r["example"] != example]
        for other in others:
            if other.is_file():
                assert screens.box_digests(other, [tuple(box)], state)[tuple(box)] != rules[0]["sha256"]


def test_the_darkness_guards_recognise_the_camp_button_row_of_the_a2_party():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_darkness.json").read_text())
    example = "WISH-2/wish2-a2/measure7/shots/12-camp.png"
    assert spec["labels"][example] == ["camp"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the stage 8 A2 measure7 shot 12 of WISH-2")
    box = [74, 417, 546, 430]
    rules = [r for r in screens.rules_of(spec["guards"]["camp"]) if r["example"] == example]
    assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == []
    assert screens.box_digests(crop, [tuple(box)], "camp")[tuple(box)] == rules[0]["sha256"]


def test_the_pool_identity_recognises_the_world_screen_of_the_new_phlan_party_of_the_f3_save():
    from tools.amiga import screens

    spec = json.loads((pathlib.Path(foundation.__file__).parent / "guards_pool.json").read_text())
    example = "WISH-1/f3accept/accept1/shots/04-world.png"
    assert spec["labels"][example] == ["world"]
    box = [326, 96, 578, 194]
    rules = [r for r in screens.rules_of(spec["identity"]["world"]) if r["example"] == example]
    assert len(rules) == 1 and rules[0]["box"] == box and rules[0]["also"] == ["camp", "camp_save_picker", "quit_prompt"]
    crop = scratch.cache_dir("acceptance") / example
    if not crop.is_file():
        pytest.skip("needs the WISH-1 f3accept world shot")
    assert screens.box_digests(crop, [tuple(box)], "world")[tuple(box)] == rules[0]["sha256"]
    # Another party's world screen must not match this rule.
    for other in screens.rules_of(spec["identity"]["world"]):
        if other["example"] != example and (scratch.cache_dir("acceptance") / other["example"]).is_file():
            digest = screens.box_digests(scratch.cache_dir("acceptance") / other["example"], [tuple(box)], "world")[tuple(box)]
            assert digest != rules[0]["sha256"]


def _vault_accept_result(tmp_path, monkeypatch, fetched_vaults):
    """`_read_title` on an accept run whose fetched disk 3 holds `fetched_vaults` in F and G."""
    staged = dos_codec.PodVault(1750, 495, 82, (bytes(63),))
    (tmp_path / "out").mkdir()
    working = tmp_path / "disk3.adf"
    _vault_disk(("B", staged)).save(working)
    _vault_disk(("F", fetched_vaults[0]), ("G", fetched_vaults[1])).save(
        tmp_path / "out" / "fetched-disk3.adf")
    monkeypatch.setattr(foundation, "walk_verdict", lambda *a, **k: {
        "place_changed": True, "squares_moved": 0, "verdicts": [], "b_ok": True,
        "d_ok": True})
    here = {"place": START, "names": NAMES, "sha256": "x"}
    title = dataclasses.replace(
        foundation.DARKNESS, read_slot=lambda disk, letter: dict(here),
        slot_letters=lambda disk: ["F", "G"], slot_files=lambda disk, letter: {})
    manifest = {"state_a": START, "names_a": NAMES,
                "registered": {}, "disks": {key: {"sha256": key} for key in title.disk_keys},
                "vault": {"items": 1, "coins": [1750, 495, 82], "sha256": "x"}}
    manifest["disks"]["disk3"]["sha256"] = hashlib.sha256(working.read_bytes()).hexdigest()
    result = {"fetched": {key: {"sha256": key if key != "disk3" else "changed"}
                          for key in title.disk_keys},
              "error": None, "completed": True, "unguarded": [], "route_changed": True}
    foundation._read_title(
        title, manifest, result, tmp_path / "out", {"disk3": working}, {}, {}, "B",
        True, False, (), False)
    return result


def test_an_accept_run_passes_when_both_saves_hold_the_staged_vault(tmp_path, monkeypatch):
    staged = dos_codec.PodVault(1750, 495, 82, (bytes(63),))
    result = _vault_accept_result(tmp_path, monkeypatch, (staged, staged))
    assert result["vault_problems"] == []
    assert result["success"] is True


def test_an_accept_run_fails_when_a_save_holds_another_vault(tmp_path, monkeypatch):
    staged = dos_codec.PodVault(1750, 495, 82, (bytes(63),))
    result = _vault_accept_result(tmp_path, monkeypatch,
                                  (staged, dos_codec.EMPTY_POD_VAULT))
    assert result["vault_problems"] == ["vault G differs from the vault staged in slot B"]
    assert result["success"] is False
