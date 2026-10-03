"""Silver Blades' `prepare --substitute`: a slot some other tool wrote, staged and judged without the JOIN party's pins."""

from __future__ import annotations

import json
import pathlib
import types

import pytest

from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance import _sha
from tests.amiga.test_amigaacceptance_accept import _accept, _manifest, _reading
from tools.amiga import acceptance, route_silver_blades
from tools.amiga.winuaesession import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep
#: The real reader, kept before the `staged` fixture replaces it.
_real_inventory = route_silver_blades._inventory

MEMBERS = [{"name": "Guy de Valois", "count": 9, "items": []},
           {"name": "MORGAINE", "count": 3, "items": []}]


# --- the command line ---------------------------------------------------------------------------


def test_the_cli_sends_a_silver_blades_substitute_to_its_own_prepare(monkeypatch, capsys):
    seen = {}

    def fake(substitute, run_id, **kw):
        seen.update(kw, substitute=substitute, run_id=run_id)
        return pathlib.Path("prepare.json")

    monkeypatch.setattr(route_silver_blades, "prepare_substitute", fake)
    monkeypatch.setattr(route_silver_blades, "prepare",
                        lambda *a, **k: pytest.fail("the JOIN prepare ran"))
    assert acceptance.main(["prepare", "--title", "ssb", "--run-id", "haste1", "--issue", "273",
                            "--substitute", "SECRETSAVE.adf", "--substitute-letter", "B"]) == 0
    assert seen == {"substitute": pathlib.Path("SECRETSAVE.adf"), "run_id": "haste1",
                    "letter": "B", "issue": "273"}
    assert capsys.readouterr().out.strip() == "prepare.json"


@pytest.mark.parametrize("extra,why", [
    ([], "requires --source or --substitute"),
    (["--source", "x.d64", "--substitute", "y.adf"], "requires --source or --substitute"),
    (["--substitute", "y.adf", "--staged-from", "j.d64"], "go with --source, not --substitute"),
    (["--substitute", "y.adf", "--save-count", "3"], "go with --source, not --substitute"),
    (["--source", "x.d64", "--substitute-letter", "B"], "--substitute-letter goes with"),
])
def test_the_cli_takes_exactly_one_silver_blades_source(monkeypatch, capsys, extra, why):
    monkeypatch.setattr(route_silver_blades, "prepare_substitute",
                        lambda *a, **k: pytest.fail("prepared"))
    monkeypatch.setattr(route_silver_blades, "prepare", lambda *a, **k: pytest.fail("prepared"))
    assert acceptance.main(["prepare", "--title", "ssb", "--run-id", "x", *extra]) == 2
    assert why in capsys.readouterr().err


# --- preparing ----------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    return tmp_path / "home"


def _substitute(tmp_path, letter="A", raw=b"converted party"):
    path = tmp_path / "SECRETSAVE.adf"
    disk = AmigaDisk.blank("Secret 1")
    disk.make_dir("/SAVE")
    disk.write_file(f"/SAVE/savgam{letter}.sav", raw)
    disk.save(path)
    return path


@pytest.mark.parametrize("run_id,letter,why", [
    ("../x", "A", "run id must use"),
    ("x", "a", "is not one capital letter"),
    ("x", "AB", "is not one capital letter"),
])
def test_a_bad_run_id_or_letter_is_refused_before_anything_is_read(
        tmp_path, home, run_id, letter, why):
    with pytest.raises(RouteError, match=why):
        route_silver_blades.prepare_substitute(_substitute(tmp_path), run_id, letter=letter)
    assert not home.exists()


def test_a_missing_substitute_or_slot_that_does_not_decode_leaves_no_run_folder(tmp_path, home):
    with pytest.raises(RouteError, match="is missing"):
        route_silver_blades.prepare_substitute(tmp_path / "absent.adf", "x")
    with pytest.raises(RouteError, match="slot A of .* does not decode"):
        route_silver_blades.prepare_substitute(_substitute(tmp_path), "x")
    with pytest.raises(RouteError, match="slot B of .* does not decode"):
        route_silver_blades.prepare_substitute(_substitute(tmp_path), "x", letter="B")
    assert not home.exists()


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """The registered disks and the slot reader replaced by synthetic ones."""
    boot, disk_b = tmp_path / "side-a.adf", tmp_path / "disk-b.adf"
    boot.write_bytes(b"registered side A")
    disk_b.write_bytes(b"registered disk B")
    monkeypatch.setattr(route_silver_blades.amigabladesjournal, "find_disk", lambda: boot)
    monkeypatch.setattr(route_silver_blades, "find_disk_b", lambda: disk_b)
    monkeypatch.setattr(route_silver_blades.staging, "SOURCE_SHA256", _sha(boot))
    monkeypatch.setattr(route_silver_blades, "DISK_B_SHA256", _sha(disk_b))
    calls = []

    def stage(source, slot, letter, out):
        calls.append((source, slot, letter))
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(out).write_bytes(b"side A with " + slot)
        return {"letter": letter}

    monkeypatch.setattr(route_silver_blades.staging, "stage_embedded_boot_disk", stage)
    party = types.SimpleNamespace(members=[dict(m) for m in MEMBERS])
    monkeypatch.setattr(route_silver_blades.amiga_savegame, "read_slot",
                        lambda disk, letter, title: party)
    monkeypatch.setattr(route_silver_blades.amiga_savegame, "state_from_savegame",
                        lambda save: types.SimpleNamespace(area=16, x=3, y=3, facing=2))
    monkeypatch.setattr(route_silver_blades, "_inventory",
                        lambda save, require_joined=True: {
                            "members": save.members, "guy_index": 0,
                            "joined_inventory_expected": False, "required": require_joined})
    return types.SimpleNamespace(boot=boot, disk_b=disk_b, calls=calls, party=party)


def test_a_substitute_slot_is_staged_as_c_on_side_a_and_recorded_with_its_letter(
        tmp_path, home, staged):
    substitute = _substitute(tmp_path, "B")
    path = route_silver_blades.prepare_substitute(substitute, "haste1", letter="B", issue="273")
    manifest = json.loads(path.read_text())
    assert path.parent.name == "haste1" and path.parent.parent.name == "273"
    assert staged.calls == [(staged.boot, b"converted party", "C")]
    assert manifest["substitute"] == {"path": str(substitute), "sha256": _sha(substitute),
                                      "letter": "B"}
    copy = pathlib.Path(manifest["published_df1"]["path"])
    assert copy.read_bytes() == substitute.read_bytes() and copy.parent == path.parent
    assert manifest["published_letter"] == "B" and manifest["slot_letter"] == "C"
    assert manifest["slot_sha256"] == manifest["published_slot_sha256"]
    assert manifest["state_a"] == {"area": 16, "x": 3, "y": 3, "facing": 2}
    # The JOIN party's 13 items and arrow stack are not asked of a substitute.
    assert manifest["inventory_a"]["required"] is False
    assert "source" not in manifest and "staged_from" not in manifest
    assert _sha(pathlib.Path(manifest["df1"]["path"])) == _sha(staged.disk_b)


class _Item(dict):
    text = "LONG SWORD"


def _save(*members):
    """A decoded save whose characters carry `count` items each."""
    return types.SimpleNamespace(characters=[
        types.SimpleNamespace(name=name, items=[_Item(type_index=1)] * count)
        for name, count in members])


def test_only_the_join_route_needs_guy_de_valois():
    save = _save(("MORGAINE", 2), ("PAINE", 0))
    with pytest.raises(RouteError, match="Guy de Valois is absent"):
        route_silver_blades._inventory(save)
    inventory = route_silver_blades._inventory(save, require_joined=False)
    assert inventory["guy_index"] is None
    assert inventory["joined_inventory_expected"] is False
    assert [(m["name"], m["count"]) for m in inventory["members"]] == [
        ("MORGAINE", 2), ("PAINE", 0)]


def test_a_substitute_party_without_guy_is_staged_if_its_first_member_carries_items(
        tmp_path, home, staged, monkeypatch):
    monkeypatch.setattr(route_silver_blades, "_inventory", _real_inventory)
    monkeypatch.setattr(route_silver_blades.amiga_savegame, "read_slot",
                        lambda disk, letter, title: _save(("MORGAINE", 2), ("PAINE", 0)))
    path = route_silver_blades.prepare_substitute(_substitute(tmp_path), "noguy")
    manifest = json.loads(path.read_text())
    assert [m["name"] for m in manifest["inventory_a"]["members"]] == ["MORGAINE", "PAINE"]
    monkeypatch.setattr(route_silver_blades.amiga_savegame, "read_slot",
                        lambda disk, letter, title: _save(("PAINE", 0), ("MORGAINE", 2)))
    with pytest.raises(RouteError, match="PAINE carries nothing"):
        route_silver_blades.prepare_substitute(_substitute(tmp_path), "noguy2")


def test_a_party_whose_first_member_carries_nothing_is_refused(tmp_path, home, staged):
    staged.party.members[0]["count"] = 0
    with pytest.raises(RouteError, match="Guy de Valois carries nothing"):
        route_silver_blades.prepare_substitute(_substitute(tmp_path), "x")
    assert not (home / ".cache").exists() or not any((home / ".cache").rglob("prepare.json"))


# --- the run ------------------------------------------------------------------------------------


def _substituted(tmp_path, letter="B"):
    """`_manifest` as `prepare_substitute` writes it: the slot sits under `letter` on the copy."""
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text())
    published = pathlib.Path(data["published_df1"]["path"])
    disk = AmigaDisk.blank("Secret 1")
    disk.make_dir("/SAVE")
    disk.write_file(f"/SAVE/savgam{letter}.sav", b"composed save")
    disk.save(published)
    substitute = tmp_path / "SECRETSAVE.adf"
    substitute.write_bytes(published.read_bytes())
    data["published_df1"]["sha256"] = _sha(published)
    data["published_letter"] = letter
    data["substitute"] = {"path": str(substitute), "sha256": _sha(substitute), "letter": letter}
    manifest.write_text(json.dumps(data))
    return manifest


@pytest.fixture
def unjoined(monkeypatch):
    """Slot readings of a party that is not the JOIN party: its inventory is not Guy's 13 items."""
    by_letter = {"B": _reading(), "D": _reading(y=7)}
    for reading in by_letter.values():
        reading["inventory"] = {"members": [], "joined_inventory_expected": False}
        reading["effects"] = {"MORGAINE": [[39, 5, 0, 0]]}
    monkeypatch.setattr(acceptance, "_slot_reading", lambda fetched, letter: by_letter[letter])
    return by_letter


def test_a_substituted_accept_reads_its_slot_under_its_letter_and_skips_the_join_check(
        tmp_path, clock, unjoined):
    _, result = _accept(tmp_path, clock, manifest=_substituted(tmp_path))
    assert result["error"] == ""
    assert result["menu_save_problems"] == [] and result["camp_save_problems"] == []
    assert result["substitute_unchanged"] is True
    assert result["success"] is True
    assert result["read"]["effects"] == {"B": {"MORGAINE": [[39, 5, 0, 0]]},
                                         "D": {"MORGAINE": [[39, 5, 0, 0]]}}


def test_the_join_check_still_holds_for_a_run_with_no_substitute(tmp_path, clock, unjoined):
    _, result = _accept(tmp_path, clock)
    assert result["menu_save_problems"] == [
        "slot B is not Guy with 13 items and one +1 arrow stack of 35"]
    assert result["success"] is False


def test_a_substitute_changed_after_preparation_is_refused_before_the_run(tmp_path, clock):
    manifest = _substituted(tmp_path)
    (tmp_path / "SECRETSAVE.adf").write_bytes(b"changed")
    with pytest.raises(RouteError, match="substitute is missing or changed"):
        _accept(tmp_path, clock, manifest=manifest)
