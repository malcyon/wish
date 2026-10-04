"""Silver Blades' `prepare --substitute`: a slot some other tool wrote, staged and judged without the JOIN party's pins."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import types

import pytest

from goldbox import areas, geo
from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance import _audio_proof, _sha
from tests.amiga.test_amigaacceptance_accept import (
    _accept,
    _manifest,
    _reading,
    _record_cli,
)
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
    # A party that has set out and stands on the start square, as WISH-273's did.
    state = types.SimpleNamespace(area=16, x=3, y=3, facing=2, set_out=True,
                                  title=areas.SECRET_OF_THE_SILVER_BLADES)
    monkeypatch.setattr(route_silver_blades.amiga_savegame, "state_from_savegame",
                        lambda save: state)
    monkeypatch.setattr(route_silver_blades, "_inventory",
                        lambda save, require_joined=True: {
                            "members": save.members, "guy_index": 0,
                            "joined_inventory_expected": False, "required": require_joined})
    return types.SimpleNamespace(boot=boot, disk_b=disk_b, calls=calls, party=party,
                                 state=state)


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


# --- a substitute that runs as a title: camp steps, or a party that has not set out -----------
#
# The legacy route takes no camp steps and presses RETURN on one opening page at most, so a
# substitute with `--camp`, or one whose party has not set out, runs the published route
# instead, loading the slot staged as D and saving to C and F.

CAMP = ("items 1", "items 2")


def test_the_cli_sends_camp_steps_with_a_silver_blades_substitute(monkeypatch, capsys):
    seen = {}

    def fake(substitute, run_id, **kw):
        seen.update(kw)
        return pathlib.Path("prepare.json")

    monkeypatch.setattr(route_silver_blades, "prepare_substitute", fake)
    assert acceptance.main(["prepare", "--title", "ssb", "--run-id", "camp1", "--issue", "4",
                            "--substitute", "POOLSAVE.ADF", "--camp", "items 1;items 2"]) == 0
    assert seen == {"letter": "A", "issue": "4", "camp": CAMP}
    capsys.readouterr()
    # The JOIN prepare still takes none.
    monkeypatch.setattr(route_silver_blades, "prepare", lambda *a, **k: pytest.fail("prepared"))
    assert acceptance.main(["prepare", "--title", "ssb", "--run-id", "x", "--source", "j.d64",
                            "--camp", "items 1"]) == 2
    assert "--camp requires" in capsys.readouterr().err


def _title_prepare(tmp_path, staged, *, camp=CAMP, set_out=True):
    staged.state.set_out = set_out
    path = route_silver_blades.prepare_substitute(_substitute(tmp_path), "camp1", issue="4",
                                                  camp=camp)
    return path, json.loads(path.read_text())


def test_camp_steps_stage_the_slot_as_d_and_record_a_title_run(tmp_path, home, staged):
    path, manifest = _title_prepare(tmp_path, staged)
    assert staged.calls == [(staged.boot, b"converted party", "D")]
    assert manifest["mode"] == route_silver_blades.SUBSTITUTE_TITLE_MODE
    assert (manifest["title"], manifest["issue"]) == ("ssb", "4")
    assert manifest["loaded_letter"] == manifest["slot_letter"] == "D"
    assert manifest["names_a"] == ["Guy de Valois", "MORGAINE"]
    assert manifest["camp"] == list(CAMP)
    assert manifest["opening_scene"] is False and manifest["items_screen"] is True
    assert manifest["disks"] == {"df0": manifest["df0"], "df1": manifest["df1"]}
    assert manifest["registered"]["published"] == manifest["published_df1"]
    assert manifest["registered"]["substitute"]["path"] == manifest["substitute"]["path"]
    title = route_silver_blades.title_for_substitute(manifest)
    # Slot D loads, C is the menu save, F the camp save, and side A's own slot A is kept.
    assert title.route[2] == ("D", "loaded_menu", "key")
    assert (title.control_letter, title.after_letter, title.kept_letters) == ("C", "F", ("A",))
    assert title.turn is None and title.issue == "4"
    camped = acceptance.accept_title(title, manifest)
    at = camped.route.index(("E", "camp", "key")) + 1
    assert [key for key, _, _ in camped.route[at:]] == [
        "V", "I", "E", "E", "NP2", "V", "I", "E", "E", "NP8", "S", "F", "N"]
    assert {"camp", "camp_sheet_items", "camp_items", "camp_sheet_items_2",
            "camp_items_2"} <= camped.strict


def test_a_party_that_has_not_set_out_runs_as_a_title_with_its_opening_scene(
        tmp_path, home, staged):
    _, manifest = _title_prepare(tmp_path, staged, camp=(), set_out=False)
    assert manifest["mode"] == route_silver_blades.SUBSTITUTE_TITLE_MODE
    assert manifest["opening_scene"] is True and "camp" not in manifest
    title = route_silver_blades.title_for_substitute(manifest)
    at = title.route.index(("B", "journal", "key")) + 1
    assert title.route[at:at + 3] == route_silver_blades.OPENING_SCENE_STEPS
    assert title.interstitials == route_silver_blades.PUBLISHED_INTERSTITIALS


def test_a_party_that_has_set_out_with_no_camp_keeps_the_legacy_route(tmp_path, home, staged):
    path = route_silver_blades.prepare_substitute(_substitute(tmp_path), "legacy1")
    manifest = json.loads(path.read_text())
    assert "mode" not in manifest and manifest["slot_letter"] == "C"
    assert not acceptance._substitute_mode(path)


def test_a_title_run_s_first_member_with_nothing_is_visited_without_items(
        tmp_path, home, staged):
    staged.party.members[0]["count"] = 0
    _, manifest = _title_prepare(tmp_path, staged, camp=("items 2",))
    assert manifest["items_screen"] is False
    title = route_silver_blades.title_for_substitute(manifest)
    assert ("I", "items", "key") not in title.route


@pytest.mark.parametrize("camp,why", [
    (("items 3",), "lines 1 to 2 only"),
    (("display",), "built for Curse and Pool of Radiance only"),
    (("join 2 17",), "rows 1 to 16 only"),
])
def test_camp_steps_the_route_cannot_drive_leave_no_run_folder(tmp_path, home, staged, camp, why):
    with pytest.raises(RouteError, match=why):
        route_silver_blades.prepare_substitute(_substitute(tmp_path), "camp1", camp=camp)
    assert staged.calls == [] and not home.exists()


def test_a_title_manifest_that_disagrees_with_its_slot_is_refused(tmp_path, home, staged):
    _, manifest = _title_prepare(tmp_path, staged)
    staged.state.set_out = False
    with pytest.raises(RouteError, match="opening_scene disagrees with the substitute's slot"):
        route_silver_blades.title_for_substitute(manifest)
    staged.state.set_out = True
    for key, value, why in (("loaded_letter", "C", "loads slot D"),
                            ("items_screen", False, "items_screen disagrees"),
                            ("names_a", ["MORGAINE"], "names_a disagrees")):
        with pytest.raises(RouteError, match=why):
            route_silver_blades.title_for_substitute({**manifest, key: value})


def test_the_cli_runs_a_title_manifest_as_its_title_and_not_the_legacy_route(
        tmp_path, monkeypatch, capsys):
    seen, _guest = _record_cli(monkeypatch)
    title = route_silver_blades.substitute_title(issue="4", items_screen=True,
                                                 opening_scene=True)
    monkeypatch.setattr(route_silver_blades, "title_for_substitute", lambda manifest: title)
    manifest = tmp_path / "prepare.json"
    manifest.write_text(json.dumps({"mode": route_silver_blades.SUBSTITUTE_TITLE_MODE}))
    assert acceptance.main(["accept", "--title", "ssb", "--manifest", str(manifest),
                            "--guards", "g.json", "--identity", "i.json",
                            "--journal-python", "python", "--audio-proof", "mute.json"]) == 0
    _, kw = seen[0]
    assert kw["title"] is title and kw["accept"] is True and kw["journal_python"] == "python"
    # The legacy route's own waits are not forced on a title run.
    assert "min_waits" not in kw and "route" not in kw
    assert acceptance.main(["measure", "--title", "ssb", "--manifest", str(manifest),
                            "--audio-proof", "mute.json", "--route", "P:party_menu"]) == 2
    assert "uses its own route" in capsys.readouterr().err


# --- a title run against the game's screens --------------------------------------------------

SUB_NAMES = ["ALPHA", "BETA"]
SSB_START = {"area": 16, "x": 3, "y": 3, "facing": geo.SOUTH}
# Screen after each (screen, key); camp keys are handled by the guest itself.
SUB_SCREENS = {
    ("title", "P"): "party_menu", ("party_menu", "L"): "load_picker",
    ("load_picker", "D"): "loaded_menu", ("loaded_menu", "V"): "sheet",
    ("sheet", "I"): "items", ("items", "E"): "sheet", ("sheet", "E"): "loaded_menu",
    ("loaded_menu", "S"): "save_picker", ("save_picker", "C"): "loaded_menu",
    ("loaded_menu", "B"): "journal", ("treasure_bar", "E"): "treasure",
    ("world", "NP8"): "world", ("world", "E"): "camp", ("camp", "S"): "camp_save_picker",
    ("camp_save_picker", "F"): "exit_game", ("exit_game", "N"): "camp",
}
SUB_STATES = {"title", "party_menu", "load_picker", "loaded_menu", "sheet", "items",
              "save_picker", "journal", "continue", "treasure_bar", "treasure", "world", "camp",
              "camp_save_picker", "exit_game", "camp_sheet_items", "camp_sheet_items_2",
              "camp_items", "camp_items_2"}


class SubstituteGuest(measure.ScreenGuest):
    """Silver Blades for a party that has not set out, loaded from slot D of DF0.

    BEGIN shows the journal, which `answer` turns into nine pages and the treasure bar; NO at
    the treasure offer shows three more pages, then the world. In camp NP2 and NP8 move the
    highlight, `V` shows that line's sheet with ITEMS, and `I` its item list. Each crop holds
    the name of the state the screen is.
    """

    def __init__(self, clock, *, drop_line=None):
        super().__init__(clock)
        self.screen, self.pages, self.then, self.line = "title", 0, None, 1
        self.place, self.mounted, self.drop_line = dict(SSB_START), [], drop_line

    def start(self, holder, *drives, timeout=None, options=()):
        self.calls.append(("start", holder, *drives))
        self.mounted = list(drives)
        return "ok pid=1"

    def get(self, remote, local, timeout=None):
        self.calls.append(("get", remote, str(local)))
        local.write_bytes(self.remote[remote])

    def stop(self, holder, timeout=None):
        return "ok stopped"

    def release(self, holder, timeout=None):
        return f"ok released by {holder}"

    def pages_of(self, count, then):
        self.screen, self.pages, self.then = "continue", count, then

    def _write(self, letter):
        remote = next(r for r in self.mounted if r and r.endswith("-df0.adf"))
        disk = AmigaDisk(self.remote[remote])
        disk.write_file(f"/SAVE/savgam{letter}.sav", _sub_slot(self.place))
        self.remote[remote] = disk.to_bytes()

    def _shown(self):
        tail = "" if self.line == 1 else f"_{self.line}"
        return {"camp_sheet": f"camp_sheet_items{tail}", "camp_list": f"camp_items{tail}"}.get(
            self.screen, self.screen)

    def press(self, holder, key, timeout=None):
        super().press(holder, key, timeout)
        screen = self.screen
        if screen == "continue" and key == "RET":
            self.pages -= 1
            if self.pages == 0:
                self.screen = self.then
        elif (screen, key) == ("treasure", "N"):
            self.pages_of(3, "world")
        elif screen == "camp" and key in ("NP2", "NP8"):
            self.line = max(1, min(len(SUB_NAMES), self.line + (1 if key == "NP2" else -1)))
        elif screen == "camp" and key == "V":
            self.screen = "camp_sheet"
        elif screen == "camp_sheet" and key == "I" and self.line != self.drop_line:
            self.screen = "camp_list"
        elif (screen, key) == ("camp_list", "E"):
            self.screen = "camp_sheet"
        elif (screen, key) == ("camp_sheet", "E"):
            self.screen = "camp"
        else:
            self.screen = SUB_SCREENS.get((screen, key), screen)
        if (screen, key) == ("world", "NP8"):
            dx, dy = geo.STEP[self.place["facing"]]
            self.place = dict(self.place, x=self.place["x"] + dx, y=self.place["y"] + dy)
        if (screen, key) in (("save_picker", "C"), ("camp_save_picker", "F")):
            self._write(key)

    def capture(self, state, raw, cropped, timeout=None):
        self.calls.append(("capture", state))
        raw.write_bytes(b"raw")
        cropped.write_bytes(self._shown().encode())

    def grab(self, state, raw, cropped, timeout=None):
        self.capture(state, raw, cropped)
        return True


class SubstituteGuard:
    """Recognises a screen by the state name the guest wrote into its crop."""

    def __contains__(self, state):
        return state in SUB_STATES

    def __call__(self, state, path):
        return path.read_bytes() == state.encode()


class SubstituteIdentity:
    """Identity rules for the sheet, the loaded menu and both item lists, each recorded."""

    def __init__(self):
        self.checked = []

    def __contains__(self, state):
        return state in ("sheet", "loaded_menu", "camp_items", "camp_items_2")

    def __call__(self, state, path):
        self.checked.append(state)
        return True


def _sub_slot(place):
    return json.dumps({"place": place, "names": SUB_NAMES}).encode()


def _sub_read(disk, letter):
    try:
        raw = disk.read_file(f"/SAVE/savgam{letter}.sav")
    except Exception:  # noqa: BLE001 - a missing slot reads as missing
        return {"missing": True, "sha256": None}
    data = json.loads(raw)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "place": data["place"],
            "names": data["names"]}


def _sub_letters(disk):
    return sorted(e.name[6].upper() for e in disk.entries(disk.lookup("/SAVE").block)
                  if e.name.lower().startswith("savgam"))


def _sub_files(disk, letter):
    return {f"savgam{letter}.sav": disk.read_file(f"/SAVE/savgam{letter}.sav")}


def _sub_adf(path, volume, slots=()):
    disk = AmigaDisk.blank(volume)
    disk.make_dir("/SAVE")
    for letter, raw in slots:
        disk.write_file(f"/SAVE/savgam{letter}.sav", raw)
    disk.save(path)
    return {"path": str(path), "sha256": _sha(path)}


def _title_run(tmp_path, clock, monkeypatch, *, camp=CAMP, guest=None, identity=None):
    """Accept a substitute prepared as a title run, for a party that has not set out."""
    monkeypatch.setattr(route_silver_blades, "_substitute_slot", lambda *a: (
        b"", None, types.SimpleNamespace(set_out=False, title=areas.SECRET_OF_THE_SILVER_BLADES)))
    base = route_silver_blades.substitute_title(issue="4", items_screen=True, opening_scene=True)
    title = dataclasses.replace(base, read_slot=_sub_read, slot_letters=_sub_letters,
                                           slot_files=_sub_files)
    df0 = _sub_adf(tmp_path / "df0.adf", "Secret 1",
                   [("A", b'{"shipped": true}'), ("D", _sub_slot(SSB_START))])
    df1 = _sub_adf(tmp_path / "df1.adf", "Secret 2")
    registered = {key: _sub_adf(tmp_path / f"{key}.adf", key.upper(), [("A", _sub_slot(SSB_START))])
                  for key in ("substitute", "published", "boot_source", "disk_b_source")}
    members = [{"name": "ALPHA", "count": 1, "items": []},
               {"name": "BETA", "count": 2, "items": []}]
    manifest = {
        "mode": route_silver_blades.SUBSTITUTE_TITLE_MODE, "title": "ssb", "issue": "4",
        "loaded_letter": "D", "slot_letter": "D", "published_letter": "A",
        "names_a": SUB_NAMES, "state_a": SSB_START, "expected_after": None,
        "items_screen": True, "opening_scene": True, "disks": {"df0": df0, "df1": df1},
        "registered": registered, "substitute": registered["substitute"],
        "inventory_a": {"members": members},
    }
    if camp:
        manifest["camp"] = list(camp)
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    guest = guest or SubstituteGuest(clock)
    identity = identity or SubstituteIdentity()
    calls = {"preflight": 0, "answered_with": []}

    def preflight(_python):
        calls["preflight"] += 1

    def answer(_holder, adf, _timeout):
        calls["answered_with"].append(adf)
        guest.pages_of(9, "treasure_bar")
        return 0, "answered"

    result = acceptance.run_recon(
        path, guest=guest, holder="wish4-test", audio_proof=_audio_proof(tmp_path),
        title=title, guard=SubstituteGuard(), identity=identity, accept=True,
        journal_python="/usr/bin/python3", preflight=preflight, answer=answer)
    return guest, result, calls, identity


def test_a_title_run_gets_through_the_opening_scene_and_reads_both_item_lists(
        tmp_path, clock, monkeypatch):
    guest, result, calls, identity = _title_run(tmp_path, clock, monkeypatch)
    assert result["error"] == "" and result["unguarded"] == []
    assert result["success"] is True, result["read"]["verdicts"]
    assert measure._keys(guest) == (
        ["P", "L", "D", "V", "I", "E", "E", "S", "C", "B"] + ["RET"] * 9 + ["E", "N"]
        + ["RET"] * 3 + ["NP8", "NP8", "E"]
        + ["V", "I", "E", "E", "NP2", "V", "I", "E", "E", "NP8"] + ["S", "F", "N"])
    assert [entry["state"] for entry in result["camp_item_lists"]] == ["camp_items", "camp_items_2"]
    assert all(entry["identity_checked"] for entry in result["camp_item_lists"])
    assert {"camp_items", "camp_items_2"} <= set(identity.checked)
    # The journal is answered off the staged boot disk, after the private reader's check.
    assert calls["preflight"] == 1
    assert calls["answered_with"] == [pathlib.Path(tmp_path / "df0.adf")]
    assert result["read"]["verdicts"][:2] == ["slot C: did not move",
                                              "slot F: moved 2 squares from 3,3 to 3,5"]
    assert result["kept_unchanged"] == {"A": True, "D": True}


def test_a_title_run_stops_at_a_sheet_with_no_item_list(tmp_path, clock, monkeypatch):
    guest = SubstituteGuest(clock, drop_line=2)
    _, result, _, _ = _title_run(tmp_path, clock, monkeypatch, guest=guest)
    assert result["success"] is False
    assert "camp_items_2 screen was not recognized" in result["error"]
    assert "F" not in measure._keys(guest)


def test_a_title_manifest_is_never_run_on_the_legacy_route(tmp_path, clock, monkeypatch):
    first = tmp_path / "first"
    first.mkdir()
    _title_run(first, clock, monkeypatch)
    with pytest.raises(RouteError, match="needs its own title's route"):
        acceptance.run_recon(
            first / "prepare.json", guest=SubstituteGuest(clock), holder="wish4-test",
            audio_proof=_audio_proof(tmp_path), guard=SubstituteGuard(),
            identity=SubstituteIdentity(), accept=True, journal_python="/usr/bin/python3",
            preflight=lambda _python: None, answer=lambda *_: (0, "answered"))
