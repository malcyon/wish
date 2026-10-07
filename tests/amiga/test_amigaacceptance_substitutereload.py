"""Preparing a Pools of Darkness reload from the disk 3 a substitute accept run fetched, on synthetic disks."""

from __future__ import annotations

import hashlib
import json

import pytest

from goldbox import amiga_savegame, dos_codec
from goldbox.amiga_adf import AmigaDisk
from tests.amiga.test_amigaacceptance_titles import (
    NAMES,
    THREE_START,
    Three,
    _pty,
)
from tools.amiga import acceptance as foundation
from tools.amiga import winuaesession

AFTER = dict(THREE_START, x=4)
OTHER_VAULT = amiga_savegame.pod_vault_to_amiga(dos_codec.PodVault(7, 0, 0, ()))


def _substituted(tmp_path, three, monkeypatch):
    """A substitute run's folder: its working disk 3 with slot B replaced, and its prepare.json."""
    run = tmp_path / "substitute-run"
    run.mkdir()
    pinned = three.registered.to_bytes()
    images = foundation._find_images
    monkeypatch.setattr(foundation, "_find_images", lambda wanted: {
        **images({k: v for k, v in wanted.items() if k != "disk3"}),
        **({"disk3": ("disk3", pinned)} if "disk3" in wanted else {})})
    edited = AmigaDisk(pinned)
    edited.write_file("/SAVE/SavGamD.pty", _pty(THREE_START))
    edited_path = tmp_path / "edited.adf"
    edited.save(edited_path)
    disk = AmigaDisk(pinned)
    disk.write_file("/SAVE/SavGamB.pty", _pty(THREE_START))
    working = run / "disk3.adf"
    disk.save(working)
    entry = {"path": str(working), "sha256": hashlib.sha256(working.read_bytes()).hexdigest()}
    manifest = {"title": "darkness", "loaded_letter": "B", "names_a": NAMES,
                "state_a": THREE_START, "disks": {"disk3": entry}, "registered": {},
                "substitute": {"letter": "D", "path": str(edited_path),
                               "sha256": hashlib.sha256(edited_path.read_bytes()).hexdigest()}}
    path = run / "prepare.json"
    path.write_text(json.dumps(manifest))
    return path, disk


def _fetched(tmp_path, path, disk, *, g=AFTER, names=NAMES, extra=None, vault=None,
             success=True, accept=True, summary_input=None, summary_sha=None):
    """The disk 3 that run fetched, F and G added by the game, and its summary."""
    fetched = AmigaDisk(disk.to_bytes())
    fetched.write_file("/SAVE/SavGamF.pty", _pty(THREE_START, names))
    fetched.write_file("/SAVE/SavGamG.pty", _pty(g, names))
    loaded = disk.read_file("/SAVE/VaultB.DAT")
    for letter in "FG":
        fetched.write_file(f"/SAVE/Vault{letter}.DAT", vault or loaded)
    if extra:
        fetched.write_file(*extra)
    file = tmp_path / "fetched3.adf"
    fetched.save(file)
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({
        "success": success, "accept": accept, "input": str(summary_input or path),
        "fetched": {"disk3": {"sha256": summary_sha or sha}}}))
    return file, sha, summary


def test_a_substitute_reload_loads_g_compares_f_and_names_both_inputs(tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    path, disk = _substituted(tmp_path, three, monkeypatch)
    file, sha, summary = _fetched(tmp_path, path, disk)
    reload = foundation.prepare_substitute_reload("again", path, file, sha, summary, "2")
    manifest = json.loads(reload.read_text())
    assert reload.parent == tmp_path / "cache" / "acceptance" / "WISH-2" / "again"
    assert manifest["title"] == "darkness-reload"
    assert manifest["mode"] == foundation.SUBSTITUTE_RELOAD_MODE
    assert manifest["loaded_letter"] == "G" and manifest["other_letter"] == "F"
    assert manifest["state_a"] == AFTER and manifest["other_place"] == THREE_START
    assert manifest["names_a"] == NAMES
    assert manifest["disks"]["disk3"]["sha256"] == sha
    assert manifest["disks"]["disk3"]["path"] != str(file)
    assert set(manifest["registered"]) == {"accept_disk3", "substitute_disk3"}
    assert manifest["registered"]["accept_disk3"] == {"path": str(file), "sha256": sha}
    assert manifest["substitute_run"]["manifest"]["path"] == str(path)
    assert manifest["substitute_run"]["substitute"]["letter"] == "D"
    # No published mode, so the CLI runs it as the registered reload route, loading G.
    assert foundation.published_darkness_title(reload, "darkness-reload") is None
    disks, registered, loaded = foundation._title_inputs(manifest, foundation.DARKNESS_RELOAD)
    assert loaded == "G" and set(registered) == {"accept_disk3", "substitute_disk3"}


@pytest.mark.parametrize("why, kwargs, match", [
    ("same place", {"g": THREE_START}, "one place"),
    ("an extra file", {"extra": ("/SAVE/notes.dat", b"x")}, "plus slots F and G"),
    ("another vault", {"vault": OTHER_VAULT}, "vault F"),
    ("another party", {"names": ["OTHER"]}, "another party"),
    ("a failed run", {"success": False}, "successful accept run"),
    ("a measure run", {"accept": False}, "successful accept run"),
    ("another run's summary", {"summary_input": "/elsewhere/prepare.json"}, "another manifest"),
    ("another fetched disk", {"summary_sha": "0" * 64}, "another disk"),
])
def test_a_substitute_reload_blocks_inputs_that_are_not_that_run_plus_two_saves(
        tmp_path, monkeypatch, why, kwargs, match):
    three = Three(tmp_path, monkeypatch)
    path, disk = _substituted(tmp_path, three, monkeypatch)
    file, sha, summary = _fetched(tmp_path, path, disk, **kwargs)
    with pytest.raises(winuaesession.RouteError, match=match):
        foundation.prepare_substitute_reload("again", path, file, sha, summary, "2")
    assert not (tmp_path / "cache" / "acceptance" / "WISH-2" / "again").exists(), why


def test_a_substitute_reload_blocks_a_manifest_that_is_not_a_substitute_run(tmp_path, monkeypatch):
    three = Three(tmp_path, monkeypatch)
    path, disk = _substituted(tmp_path, three, monkeypatch)
    file, sha, summary = _fetched(tmp_path, path, disk)
    manifest = json.loads(path.read_text())
    for change, match in (({"substitute": None}, "not a Pools of Darkness substitute run"),
                          ({"title": "pool"}, "not a Pools of Darkness substitute run")):
        path.write_text(json.dumps({**manifest, **change}))
        with pytest.raises(winuaesession.RouteError, match=match):
            foundation.prepare_substitute_reload("again", path, file, sha, summary, "2")
    path.write_text(json.dumps(manifest))
    base = foundation.pathlib.Path(manifest["disks"]["disk3"]["path"])
    kept = base.read_bytes()
    base.write_bytes(kept[:-1] + bytes([kept[-1] ^ 1]))
    with pytest.raises(winuaesession.RouteError, match="changed from preparation"):
        foundation.prepare_substitute_reload("again", path, file, sha, summary, "2")
    base.write_bytes(kept)
    with pytest.raises(winuaesession.RouteError, match="disk 3 SHA-256 differs"):
        foundation.prepare_substitute_reload("again", path, file, "1" * 64, summary, "2")


def test_the_prepare_command_takes_a_substitute_manifest_only_for_darkness_reload(
        tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(foundation, "prepare_substitute_reload",
                        lambda *a: calls.append(a) or tmp_path / "prepare.json")
    head = ["prepare", "--run-id", "again", "--disk3", "d.adf", "--disk3-sha256", "0" * 64,
            "--accept-summary", "s.json", "--substitute-manifest", "m.json"]
    assert foundation.main([*head, "--title", "darkness-reload", "--issue", "WISH-2"]) == 0
    assert [str(a) for a in calls[0]] == ["again", "m.json", "d.adf", "0" * 64, "s.json", "WISH-2"]
    assert foundation.main([*head, "--title", "darkness"]) == 2
    assert "--substitute-manifest" in capsys.readouterr().err
    assert len(calls) == 1
    assert foundation.main(["prepare", "--run-id", "again", "--title", "darkness-reload",
                            "--substitute-manifest", "m.json"]) == 2
    assert "needs --disk3" in capsys.readouterr().err
    assert len(calls) == 1


@pytest.mark.parametrize("forge", ["another disk", "another slot", "a changed substitute"])
def test_a_substitute_reload_blocks_a_manifest_whose_disk_is_not_the_pinned_disk_with_the_substitute(
        tmp_path, monkeypatch, forge):
    three = Three(tmp_path, monkeypatch)
    path, disk = _substituted(tmp_path, three, monkeypatch)
    manifest = json.loads(path.read_text())
    if forge == "another disk":
        # An unrelated verified disk that the manifest and summary both describe consistently.
        disk.write_file("/SAVE/notes.dat", b"x")
        working = foundation.pathlib.Path(manifest["disks"]["disk3"]["path"])
        disk.save(working)
        manifest["disks"]["disk3"]["sha256"] = hashlib.sha256(working.read_bytes()).hexdigest()
    elif forge == "another slot":
        manifest["substitute"]["letter"] = "A"
    else:
        foundation.pathlib.Path(manifest["substitute"]["path"]).write_bytes(b"changed")
    path.write_text(json.dumps(manifest))
    file, sha, summary = _fetched(tmp_path, path, disk)
    with pytest.raises(winuaesession.RouteError):
        foundation.prepare_substitute_reload("again", path, file, sha, summary, "2")
    assert not (tmp_path / "cache" / "acceptance" / "WISH-2" / "again").exists()
