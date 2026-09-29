"""The Silver Blades route accepts only effect-array derivatives of its JOIN disk."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from goldbox import d64, effects
from goldbox.amiga_adf import AmigaDisk
from tests.amiga.fakes import fake_savecount
from tools.amiga import acceptance
from tools.amiga import route_silver_blades as route
from tools.amiga.winuaesession import RouteError


def _sources(tmp_path, monkeypatch):
    original = d64.D64.blank()
    payload = bytearray(0x300)
    original.write_file("SAVEDGAME0", d64.attach_load_address(0x4900, payload))
    original.write_file("OTHER", b"other file")
    join = tmp_path / "join.d64"
    original.save(join)
    monkeypatch.setattr(route, "JOIN_SHA256", route.sha256(join))
    return original, join


def _stage(tmp_path, original, change):
    staged = d64.D64.from_bytes(original.to_bytes())
    change(staged)
    source = tmp_path / "staged.d64"
    staged.save(source)
    return source


def _effect(staged):
    address, payload = d64.split_load_address(staged.read_file("SAVEDGAME0"))
    body = bytearray(payload)
    effects.write_effect(body, 63, 1, 0, 0x2F, 5)
    staged.write_file_inplace("SAVEDGAME0", d64.attach_load_address(address, body))


def test_staged_source_records_rows_in_prepare_manifest(tmp_path, monkeypatch):
    original, join = _sources(tmp_path, monkeypatch)
    source = _stage(tmp_path, original, _effect)
    boot = tmp_path / "boot.adf"
    disk_b = tmp_path / "disk-b.adf"
    original_disk = AmigaDisk.blank("Secret 1")
    original_disk.write_file("/Secret", b"synthetic executable")
    original_disk.make_dir("/SAVE")
    original_disk.write_file("/SAVE/spindisk", b"synthetic spindisk")
    original_disk.write_file("/SAVE/savgamA.sav", b"bundled slot")
    original_disk.save(boot)
    disk_b.write_bytes(b"disk b")
    monkeypatch.setattr(route.amigabladesjournal, "find_disk", lambda: boot)
    monkeypatch.setattr(route.staging, "SOURCE_SHA256", route.sha256(boot))
    monkeypatch.setattr(route, "find_disk_b", lambda: disk_b)
    monkeypatch.setattr(route, "DISK_B_SHA256", route.sha256(disk_b))
    monkeypatch.setattr(route.scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))

    from editor import roster, saveplan
    from editor.convert import Source

    monkeypatch.setattr(roster, "Party", lambda path: object())
    monkeypatch.setattr(saveplan, "prepare", lambda party: object())
    monkeypatch.setattr(Source, "of_snapshot", lambda snapshot: object())
    def resolve_assets(*args, **kwargs):
        assert kwargs["amiga_disk_one"] == boot
        return object()

    monkeypatch.setattr(saveplan, "resolve_assets", resolve_assets)
    plan = SimpleNamespace(destination=SimpleNamespace(slot="A"),
                           report=SimpleNamespace(dropped=[], losses=[]))
    monkeypatch.setattr(saveplan, "prepare_save_as", lambda *args: plan)

    def publish(plan, party):
        disk = AmigaDisk(original_disk.to_bytes())
        disk.write_file("/SAVE/savgamA.sav", b"slot")
        disk.save(tmp_path / "acceptance" / "661" / "run" / "SECRETSAVE-published.adf")

    monkeypatch.setattr(saveplan, "publish", publish)
    monkeypatch.setattr(route.amiga_savegame, "read_slot", lambda *args: object())
    monkeypatch.setattr(route, "_inventory", lambda save: {"joined_inventory_expected": True})
    monkeypatch.setattr(route.amiga_savegame, "state_from_savegame",
                        lambda save: SimpleNamespace(area=16, x=3, y=5, facing=2))

    def stage(boot_source, slot, letter, df0):
        df0.parent.mkdir(parents=True, exist_ok=True)
        df0.write_bytes(b"staged boot")
        return {"letter": letter}

    monkeypatch.setattr(route.staging, "stage_embedded_boot_disk", stage)
    manifest_path = route.prepare(source, "run", staged_from=join, issue="661")
    manifest = json.loads(manifest_path.read_text())
    assert manifest_path == tmp_path / "acceptance" / "661" / "run" / "prepare.json"
    assert manifest["source"]["path"] == str(source)
    assert manifest["staged_from"]["path"] == str(join)
    assert manifest["active_rows"] == [[63, 1, 0, 0x2F, 5]]
    assert manifest["inventory_a"]["joined_inventory_expected"] is True


@pytest.mark.parametrize("target", ["SAVEDGAME0", "OTHER"])
def test_staged_source_refuses_other_file_changes(tmp_path, monkeypatch, target):
    original, join = _sources(tmp_path, monkeypatch)

    def change(staged):
        data = bytearray(staged.read_file(target))
        data[-1] ^= 1
        staged.write_file_inplace(target, data)

    source = _stage(tmp_path, original, change)
    with pytest.raises(RouteError, match=target):
        route.prepare(source, "run", staged_from=join)


@pytest.mark.parametrize("offset", [0x0C0, 0x27F])
def test_staged_source_refuses_changes_between_effect_arrays(tmp_path, monkeypatch, offset):
    original, join = _sources(tmp_path, monkeypatch)

    def change(staged):
        address, payload = d64.split_load_address(staged.read_file("SAVEDGAME0"))
        body = bytearray(payload)
        body[offset] ^= 1
        staged.write_file_inplace("SAVEDGAME0", d64.attach_load_address(address, body))

    source = _stage(tmp_path, original, change)
    with pytest.raises(RouteError, match="outside effect arrays in SAVEDGAME0"):
        route._staged_rows(source, join)


def test_staged_from_must_be_join(tmp_path, monkeypatch):
    original, join = _sources(tmp_path, monkeypatch)
    source = _stage(tmp_path, original, _effect)
    wrong = tmp_path / "wrong.d64"
    wrong.write_bytes(source.read_bytes())
    with pytest.raises(RouteError, match="staged-from SHA-256"):
        route.prepare(source, "run", staged_from=wrong)


def test_normal_prepare_still_requires_join(tmp_path, monkeypatch):
    original, join = _sources(tmp_path, monkeypatch)
    source = _stage(tmp_path, original, _effect)
    with pytest.raises(RouteError, match="JOIN source SHA-256"):
        route.prepare(source, "run")


def test_prepare_cli_passes_staged_source_and_issue(tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(route, "prepare", lambda *args, **kwargs:
                        seen.append((args, kwargs)) or tmp_path / "prepare.json")
    assert acceptance.main(["prepare", "--title", "ssb", "--source", "source.d64", "--run-id", "run",
                                  "--staged-from", "join.d64", "--issue", "661"]) == 0
    assert seen == [((tmp_path.__class__("source.d64"), "run"),
                     {"staged_from": tmp_path.__class__("join.d64"), "issue": "661"})]
    assert capsys.readouterr().out.strip() == str(tmp_path / "prepare.json")


def test_prepare_silver_blades_requires_a_source_before_preparation(monkeypatch):
    monkeypatch.setattr(route, "prepare", lambda *args, **kwargs:
                        pytest.fail("prepare was called"))
    assert acceptance.main(["prepare", "--title", "ssb", "--run-id", "run"]) == 2


def test_silver_blades_prepare_refuses_other_titles_options_before_preparation(monkeypatch):
    monkeypatch.setattr(route, "prepare", lambda *args, **kwargs:
                        pytest.fail("prepare was called"))
    assert acceptance.main(["prepare", "--title", "ssb", "--source", "source.d64",
                            "--run-id", "run", "--disk3", "disk3.adf"]) == 2


def _prepared(tmp_path, monkeypatch, **kwargs):
    """`prepare` on a synthetic JOIN disk, as `test_staged_source_records_rows...` builds it."""
    original, join = _sources(tmp_path, monkeypatch)
    boot = tmp_path / "boot.adf"
    disk_b = tmp_path / "disk-b.adf"
    original_disk = AmigaDisk.blank("Secret 1")
    original_disk.write_file("/Secret", b"synthetic executable")
    original_disk.make_dir("/SAVE")
    original_disk.write_file("/SAVE/spindisk", b"synthetic spindisk")
    original_disk.write_file("/SAVE/savgamA.sav", b"bundled slot")
    original_disk.save(boot)
    disk_b.write_bytes(b"disk b")
    monkeypatch.setattr(route.amigabladesjournal, "find_disk", lambda: boot)
    monkeypatch.setattr(route.staging, "SOURCE_SHA256", route.sha256(boot))
    monkeypatch.setattr(route, "find_disk_b", lambda: disk_b)
    monkeypatch.setattr(route, "DISK_B_SHA256", route.sha256(disk_b))
    monkeypatch.setattr(route.scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    from editor import roster, saveplan
    from editor.convert import Source

    monkeypatch.setattr(roster, "Party", lambda path: object())
    monkeypatch.setattr(saveplan, "prepare", lambda party: object())
    monkeypatch.setattr(Source, "of_snapshot", lambda snapshot: object())
    monkeypatch.setattr(saveplan, "resolve_assets", lambda *args, **kw: object())
    plan = SimpleNamespace(destination=SimpleNamespace(slot="A"),
                           report=SimpleNamespace(dropped=[], losses=[]))
    monkeypatch.setattr(saveplan, "prepare_save_as", lambda *args: plan)

    def publish(plan, party):
        disk = AmigaDisk(original_disk.to_bytes())
        disk.write_file("/SAVE/savgamA.sav", b"slot")
        disk.save(tmp_path / "acceptance" / "672" / "run" / "SECRETSAVE-published.adf")

    monkeypatch.setattr(saveplan, "publish", publish)
    monkeypatch.setattr(route.amiga_savegame, "read_slot", lambda *args: object())
    monkeypatch.setattr(route, "_inventory", lambda save: {"joined_inventory_expected": True})
    monkeypatch.setattr(route.amiga_savegame, "state_from_savegame",
                        lambda save: SimpleNamespace(area=16, x=3, y=5, facing=2))
    staged_slots = []

    def stage(boot_source, slot, letter, df0):
        staged_slots.append(slot)
        df0.parent.mkdir(parents=True, exist_ok=True)
        df0.write_bytes(b"staged boot")
        return {"letter": letter}

    monkeypatch.setattr(route.staging, "stage_embedded_boot_disk", stage)
    manifest_path = route.prepare(join, "run", **kwargs)
    return json.loads(manifest_path.read_text()), staged_slots


def test_prepare_without_a_save_count_stages_the_slot_untouched(tmp_path, monkeypatch):
    manifest, staged = _prepared(tmp_path, monkeypatch)
    assert staged == [b"slot"]
    assert "save_count" not in manifest
    assert manifest["slot_sha256"] == route.hashlib.sha256(b"slot").hexdigest()


def test_prepare_with_a_save_count_stages_the_edited_slot(tmp_path, monkeypatch):
    wheel = tmp_path / "wheel"
    fake_savecount(wheel)
    monkeypatch.setattr(route.amigabladesjournal, "wheel_repo", lambda: wheel)
    manifest, staged = _prepared(tmp_path, monkeypatch, save_count=29)
    assert staged == [b"slot|count=29"]
    assert manifest["save_count"] == 29
    assert manifest["slot_sha256"] == route.hashlib.sha256(b"slot|count=29").hexdigest()
    published = AmigaDisk.open(tmp_path / "acceptance" / "672" / "run" / "SECRETSAVE-published.adf")
    assert published.read_file("/SAVE/savgamA.sav") == b"slot"


def test_a_save_count_the_helper_refuses_is_a_route_error(tmp_path, monkeypatch):
    wheel = tmp_path / "wheel"
    fake_savecount(wheel, refuse=True)
    monkeypatch.setattr(route.amigabladesjournal, "wheel_repo", lambda: wheel)
    with pytest.raises(RouteError, match="save count 30 refused"):
        _prepared(tmp_path, monkeypatch, save_count=30)


def test_a_save_count_without_the_private_repository_is_a_route_error(tmp_path, monkeypatch):
    monkeypatch.setattr(route.amigabladesjournal, "wheel_repo", lambda: tmp_path / "absent")
    with pytest.raises(RouteError, match="WISH_CODEWHEEL"):
        _prepared(tmp_path, monkeypatch, save_count=29)


def test_a_savecount_that_imports_a_sibling_module_loads(tmp_path, monkeypatch):
    wheel = tmp_path / "wheel"
    fake_savecount(wheel, sibling=True)
    monkeypatch.setattr(route.amigabladesjournal, "wheel_repo", lambda: wheel)
    manifest, staged = _prepared(tmp_path, monkeypatch, save_count=7)
    assert staged == [b"slot|count=7"]
    assert str(wheel / "ssb" / "analysis") not in route.sys.path


@pytest.mark.parametrize("body", ["def broken(:\n", "import no_such_module_here\n",
                                  "raise KeyError('secret')\n"])
def test_a_savecount_that_fails_to_load_is_a_route_error_naming_only_the_type(
        tmp_path, monkeypatch, body):
    analysis = tmp_path / "wheel" / "ssb" / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "savecount.py").write_text(body)
    monkeypatch.setattr(route.amigabladesjournal, "wheel_repo", lambda: tmp_path / "wheel")
    with pytest.raises(RouteError,
                       match="failed to load: (SyntaxError|ModuleNotFoundError|KeyError)") as info:
        _prepared(tmp_path, monkeypatch, save_count=1)
    assert "secret" not in str(info.value)
    assert "no_such_module_here" not in str(info.value)
