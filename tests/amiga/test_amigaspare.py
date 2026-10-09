"""A Pools of Darkness run with a spare save disk: staged by `prepare --spare-disk`, put in DF1 by `swap-df1`."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib

import pytest

from goldbox import amiga_pod, amiga_savegame, dos_codec
from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_accept import MapGuard, _IdentityMap
from tests.amiga.test_amigaacceptance_title import (
    NAMES,
    TitleGuest,
    _files,
    _letters,
    _read_slot,
    _slot,
)
from tests.amiga.test_amigaacceptance_titles import DARK_START, DARK_STATES
from tools.amiga import acceptance, route_darkness, screens
from tools.amiga.route_darkness import SPARE, swap_df1
from tools.amiga.winuaesession import RouteError
from tools.registry import scratch

clock = measure.clock  # the fixture that replaces the driver's time and sleep

#: A vault of two items and some coins, as the converter writes it.
HELD = dos_codec.PodVault(1750, 495, 82, (bytes(63), bytes([1]) + bytes(62)))
HELD_BYTES = amiga_savegame.pod_vault_to_amiga(HELD)
EMPTY_BYTES = amiga_savegame.pod_vault_to_amiga(dos_codec.EMPTY_POD_VAULT)
VAULT_LETTERS = "ABCDEFGHT"


def _readers(title):
    return dataclasses.replace(title, read_slot=_read_slot, slot_letters=_letters,
                               slot_files=_files)


def _disk(volume, slots=(), vaults=None):
    """A disk with a `SAVE` drawer, JSON saved games and real vault files."""
    disk = AmigaDisk.blank(volume)
    disk.make_dir("/SAVE")
    for letter, raw in slots:
        disk.write_file(f"/SAVE/savgam{letter}.sav", raw)
    for letter, data in (vaults or {}).items():
        disk.write_file(f"/SAVE/Vault{letter}.DAT", data)
    return disk


def _entry(path, disk):
    path.write_bytes(disk.to_bytes())
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _empty_vaults():
    return {letter: EMPTY_BYTES for letter in VAULT_LETTERS}


def _accept_manifest(tmp_path):
    slots = [(c, _slot(dict(DARK_START, x=5) if c != "B" else DARK_START)) for c in "ABCDE"]
    disks = {"disk1": _entry(tmp_path / "disk1.adf", _disk("POD 1")),
             "disk2": _entry(tmp_path / "disk2.adf", _disk("POD 2")),
             "disk3": _entry(tmp_path / "disk3.adf",
                             _disk("POD 3", slots, {**_empty_vaults(), "B": HELD_BYTES})),
             SPARE: _entry(tmp_path / "spare.adf", _disk("Empty", (), _empty_vaults()))}
    data = {"disks": disks, "registered": {}, "loaded_letter": "B", "state_a": DARK_START,
            "names_a": NAMES, "vault": {"items": 2, "coins": [1750, 495, 82], "sha256": "x"},
            SPARE: {"path": "/elsewhere/minimal.adf", "sha256": disks[SPARE]["sha256"]}}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(data))
    return path


class DriveGuest(TitleGuest):
    """The game saves to the disk in DF1: the slot, then the loaded slot's vault on that disk copied to the new letter.

    Like the lane, an insert names the file's hash, and a wrong one is recorded and the insert raises
    a RouteError.
    """

    def __init__(self, clock, *, loaded="B", to_drive=1, writes=("F", "G")):
        super().__init__(clock)
        self.loaded, self.to_drive, self.writes, self.bad_hash = loaded, to_drive, writes, []

    def insert(self, holder, drive_number, remote, timeout=None, sha256=None):
        if hashlib.sha256(self.remote[remote]).hexdigest() != sha256:
            self.bad_hash.append((drive_number, remote, sha256))
            raise RouteError(f"{remote} does not hash to {sha256}")
        return super().insert(holder, drive_number, remote, timeout, sha256)

    def press(self, holder, key, timeout=None):
        super(TitleGuest, self).press(holder, key, timeout)
        if key in self.writes:
            remote = self.mounted[self.to_drive]
            disk = AmigaDisk(self.remote[remote])
            disk.write_file(f"/SAVE/savgam{key}.sav", _slot(DARK_START))
            vault = disk.read_file(f"/SAVE/Vault{self.loaded}.DAT")
            disk.remove_file(f"/SAVE/Vault{key}.DAT")
            disk.write_file(f"/SAVE/Vault{key}.DAT", vault)
            self.remote[remote] = disk.to_bytes()


def _spare_vault_title():
    return route_darkness.spare_save_title(_readers(route_darkness.vault_title(2, True)))


def _accept(tmp_path, clock, guest=None, title=None):
    title = title or _spare_vault_title()
    guest = guest or DriveGuest(clock)
    states = {*DARK_STATES, *(state for _, state, _ in title.route)}
    result = acceptance.run_recon(
        _accept_manifest(tmp_path), guest=guest, guard=MapGuard(states=tuple(states)),
        identity=_IdentityMap(), holder="wish679-test", audio_proof=_audio_proof(tmp_path),
        title=title, accept=True, attempt="accept1")
    return guest, result


def _keys(guest):
    return [c[2] if c[0] == "press" else ("insert", c[1], c[2].rsplit("-", 1)[1])
            for c in guest.calls if c[0] in ("press", "insert")]


# The route.

def test_swap_df1_puts_the_disk_in_drive_1_before_the_steps_key():
    assert swap_df1(SPARE, ("S", "camp_save_picker", "key")) == (
        (1, SPARE, "S"), "camp_save_picker", "insert")
    for step in (("G", "exit_game", "write"), ((1, "disk3", "N"), "camp", "insert")):
        with pytest.raises(RouteError, match="goes before a key step"):
            swap_df1(SPARE, step)


def test_the_spare_save_route_swaps_the_spare_in_for_the_camp_save_and_disk_3_back_after_it():
    vault = route_darkness.DARKNESS_VAULT
    title = route_darkness.spare_save_title(vault)
    assert title.spares == ("disk2", SPARE) and title.mounted == ("disk1", "disk3")
    changed = [(a, b) for a, b in zip(vault.route, title.route, strict=True) if a != b]
    assert changed == [
        (("S", "camp_save_picker", "key"), ((1, SPARE, "S"), "camp_save_picker", "insert")),
        (("N", "camp", "key"), ((1, "disk3", "N"), "camp", "insert"))]
    # The control save at the loaded menu is untouched, so it goes to disk 3.
    assert ("F", "loaded_menu", "write") in title.route
    assert title.measure_route[-1] == ((1, SPARE, "S"), "camp_save_picker", "insert")
    assert route_darkness.spare_save_title(route_darkness.DARKNESS).route[-3:] == (
        ((1, SPARE, "S"), "camp_save_picker", "insert"), ("G", "exit_game", "write"),
        ((1, "disk3", "N"), "camp", "insert"))
    with pytest.raises(RouteError, match="already has a spare"):
        route_darkness.spare_save_title(title)


def test_a_route_without_a_camp_save_has_nothing_to_make_on_the_spare():
    with pytest.raises(RouteError, match="no camp save"):
        route_darkness.spare_save_title(route_darkness.DARKNESS_RELOAD)


@pytest.mark.parametrize(("items", "coins", "tail"), [
    (2, True, (("S", "vault_bar", "key"), ("T", "vault_take", "key"), ("I", "vault_items", "key"),
               ("NP2", "vault_row", "key"), ("E", "vault_take", "key"), ("E", "vault_bar", "key"),
               ("E", "elminster_menu", "key"))),
    (0, False, (("S", "vault_bar", "key"), ("T", "vault_empty", "key"))),
])
def test_the_spare_reload_loads_from_the_spare_answers_disk_3_then_disk_2_and_opens_the_vault(
        items, coins, tail):
    title = route_darkness.spare_reload_title("G", items, coins)
    assert title.route == (
        ("P", "party_menu", "key"), ((1, SPARE, "L"), "load_from", "insert"),
        ("P", "load_picker", "key"), ("G", "disk3_prompt", "key"),
        ((1, "disk3", "SPACE"), "disk2_prompt", "insert"), route_darkness.DISK2_INSERT,
        ("V", "sheet", "key"), ("E", "loaded_menu", "key"), ("B", "journal", "key"),
        ("X", "journal_answer", "key"), ("RET", "elminster_menu", "key"), *tail)
    assert title.save_disk == SPARE and title.spares == ("disk2", SPARE)
    # Two free letters that no step presses, as a measure run's title needs.
    assert (title.control_letter, title.after_letter) == ("F", "H")
    assert {"disk3_prompt", "elminster_menu"} <= title.strict
    assert not any(kind == "write" for _, _, kind in title.route)


SPARE_RUN_SHOTS = scratch.cache_dir("acceptance") / "WISH-2" / "wish2-spare-r1" / "r1" / "shots"


def test_the_darkness_guards_recognise_the_insert_disk_3_prompt_and_not_the_disk_2_one():
    rules = json.loads(pathlib.Path(route_darkness.__file__).with_name(
        "guards_darkness.json").read_text())["guards"]
    assert "disk3_prompt" in rules
    shot, other = SPARE_RUN_SHOTS / "04-disk3_prompt.png", SPARE_RUN_SHOTS / "05-disk2_prompt.png"
    if not (shot.exists() and other.exists()):
        pytest.skip("the spare run's shots are not on this machine")
    guards = screens.PixelGuards.__new__(screens.PixelGuards)
    guards.rules = {name: rules[name] for name in ("disk3_prompt", "disk2_prompt")}
    assert guards("disk3_prompt", shot) and not guards("disk2_prompt", shot)
    assert guards("disk2_prompt", other) and not guards("disk3_prompt", other)


# Preparing the accept run.

@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """Disk 3 as the registered one for the run: `_find_images` hands back composed disks."""
    disk3 = _disk(route_darkness.DARKNESS_VOLUME).to_bytes()
    images = {"disk1": ("d1", b"one"), "disk2": ("d2", b"two"), "disk3": ("d3", disk3)}
    for key, name in (("disk1", "DARKNESS_DISK1_SHA256"), ("disk2", "DARKNESS_DISK2_SHA256"),
                      ("disk3", "DARKNESS_DISK3_SHA256")):
        monkeypatch.setattr(route_darkness, name, hashlib.sha256(images[key][1]).hexdigest())
    monkeypatch.setattr(route_darkness, "_find_images",
                        lambda wanted: {k: images[k] for k in wanted})
    monkeypatch.setattr(route_darkness.scratch, "ensure", lambda path: path.mkdir(parents=True))
    monkeypatch.setattr(route_darkness, "_darkness_read_slot",
                        lambda disk, letter: {"sha256": "s", "names": NAMES, "place": DARK_START})
    monkeypatch.setattr(route_darkness, "DARKNESS", dataclasses.replace(
        route_darkness.DARKNESS, read_slot=lambda disk, letter: {
            "sha256": "s", "names": NAMES, "place": DARK_START}))
    return tmp_path


def test_a_spare_is_copied_into_the_run_and_recorded(pinned):
    spare = pinned / "minimal.adf"
    _disk("Empty", (), _empty_vaults()).save(spare)
    manifest = route_darkness._prepare_darkness(pinned / "run", None, "B", spare=spare)
    working = pinned / "run" / "spare.adf"
    assert working.read_bytes() == spare.read_bytes()
    assert manifest["disks"][SPARE] == {"path": str(working), "sha256": manifest[SPARE]["sha256"]}
    assert manifest[SPARE]["path"] == str(spare) and manifest[SPARE]["volume"] == "Empty"
    assert "/SAVE/VaultT.DAT" in manifest[SPARE]["files"]
    json.dumps(manifest)
    plain = route_darkness._prepare_darkness(pinned / "run2", None, "B")
    assert SPARE not in plain and SPARE not in plain["disks"]


def _with_save(path):
    disk = _disk("Empty", (), _empty_vaults())
    disk.write_file("/SAVE/SavGamC.pty", b"x")
    disk.save(path)


@pytest.mark.parametrize("make", [
    lambda path: _with_save(path),
    lambda path: AmigaDisk.blank("Empty").save(path),
    lambda path: None,
])
def test_a_spare_that_holds_a_save_has_no_save_drawer_or_is_missing_writes_no_run(pinned, make):
    spare = pinned / "spare.adf"
    make(spare)
    with pytest.raises(RouteError, match="spare disk"):
        route_darkness._prepare_darkness(pinned / "run", None, "B", spare=spare)
    assert not (pinned / "run").exists()


def test_prepare_passes_a_spare_only_to_the_titles_that_take_one(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    seen = []

    def fake(run, specimen, **kw):
        seen.append(kw)
        scratch.ensure(run)
        return {"title": "darkness", "names_a": NAMES}

    monkeypatch.setattr(acceptance, "_PREPARE", {"darkness-vault": fake, "darkness": fake,
                                                 "darkness-unstarted": fake})
    spare = tmp_path / "s.adf"
    acceptance.prepare(acceptance.DARKNESS_VAULT, "r1", spare=spare)
    acceptance.prepare(acceptance.DARKNESS, "r2")
    assert seen == [{"substitute": None, "substitute_letter": "A", "spare": spare},
                    {"substitute": None, "substitute_letter": "A"}]
    with pytest.raises(RouteError, match="--spare-disk is for"):
        acceptance.prepare(acceptance.DARKNESS_UNSTARTED, "r3", spare=spare)
    with pytest.raises(RouteError, match="without camp"):
        acceptance.prepare(acceptance.DARKNESS, "r4", spare=spare, camp=("view 1",))


def test_the_cli_hands_the_spare_to_prepare_and_blocks_it_on_a_published_disk(
        tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(acceptance, "prepare",
                        lambda title, run_id, **kw: seen.append((title, kw)) or tmp_path / "p.json")
    assert acceptance.main(["prepare", "--title", "darkness-vault", "--run-id", "r",
                            "--substitute", "s.adf", "--spare-disk", "m.adf"]) == 0
    assert seen[0][0] is acceptance.DARKNESS_VAULT
    assert seen[0][1]["spare"] == pathlib.Path("m.adf")
    assert acceptance.main(["prepare", "--title", "darkness", "--run-id", "r"]) == 0
    assert "spare" not in seen[1][1]
    for extra in (["--published-disk-three", "--saveas-report", "r.json"],
                  ["--published-disk-one", "--saveas-report", "r.json"]):
        assert acceptance.main(["prepare", "--title", "darkness", "--run-id", "r",
                                "--spare-disk", "m.adf", *extra]) == 2
    assert acceptance.main(["prepare", "--title", "pool", "--run-id", "r",
                            "--spare-disk", "m.adf"]) == 2
    assert len(seen) == 2


# The accept run.

def test_the_camp_save_goes_to_the_spare_and_disk_3_goes_back_at_its_current_hash(
        tmp_path, clock):
    guest, result = _accept(tmp_path, clock)
    assert result["error"] == "" and result["success"] is True, result.get("read")
    keys = _keys(guest)
    at = keys.index(("insert", 1, "spare.adf"))
    assert keys[at - 1] == "R" and keys[at + 1:] == ["S", "G", ("insert", 1, "disk3.adf"), "N"]
    assert guest.bad_hash == []
    rehashed = [e for e in result["events"] if "rehashed" in e]
    assert [e["rehashed"] for e in rehashed] == ["disk3"]
    manifest = json.loads((tmp_path / "prepare.json").read_text())
    assert rehashed[0]["sha256"] != manifest["disks"]["disk3"]["sha256"]
    # F went to disk 3 and G to the spare, each with the vault the disk in DF1 held for B.
    disk3 = AmigaDisk.open(tmp_path / "accept1" / "fetched-disk3.adf")
    spare = AmigaDisk.open(tmp_path / "accept1" / f"fetched-{SPARE}.adf")
    assert _letters(disk3) == list("ABCDEF") and _letters(spare) == ["G"]
    assert result["vault_problems"] == [] and result["spare_extra_saves"] == []
    found = result["spare_vault"]
    assert found["spare"]["items"] == 0 and found["spare_matches_staged"] is False
    assert found["disk3_control"]["items"] == 2 and found["disk3_control_matches_staged"] is True
    assert found["disk3"] == {"items": 0, "coins": [0, 0, 0],
                              "sha256": hashlib.sha256(EMPTY_BYTES).hexdigest()}
    assert result["read"]["verdicts"][-1] == (
        "vault G on the spare disk: 0 item rows and coins [0, 0, 0], not the vault staged in "
        "slot B")


def test_a_spare_vault_like_the_staged_one_is_recorded_and_judges_nothing(tmp_path, clock):
    class FromMemory(DriveGuest):
        """The game writes the loaded vault from memory, whatever disk is in DF1."""

        def press(self, holder, key, timeout=None):
            super().press(holder, key, timeout)
            if key == "G":
                remote = self.mounted[1]
                disk = AmigaDisk(self.remote[remote])
                disk.remove_file("/SAVE/VaultG.DAT")
                disk.write_file("/SAVE/VaultG.DAT", HELD_BYTES)
                self.remote[remote] = disk.to_bytes()

    _, result = _accept(tmp_path, clock, guest=FromMemory(clock))
    assert result["success"] is True and result["spare_vault"]["spare_matches_staged"] is True
    assert result["read"]["verdicts"][-1].endswith(", the same as the vault staged in slot B")


def test_a_camp_save_that_lands_on_disk_3_fails_the_spare_run(tmp_path, clock):
    class StaysOnThree(DriveGuest):
        def press(self, holder, key, timeout=None):
            if key == "G":
                self.to_drive, self.mounted = 1, [self.mounted[0], self.three]
            super().press(holder, key, timeout)

        def start(self, holder, *drives, timeout=None, options=()):
            self.three = drives[1]
            return super().start(holder, *drives, timeout=timeout, options=options)

    _, result = _accept(tmp_path, clock, guest=StaysOnThree(clock))
    assert result["completed"] is True and result["success"] is False
    assert result["disks_unchanged"][SPARE] is True


def test_a_spare_manifest_does_not_run_on_a_route_without_the_spare(tmp_path, clock):
    with pytest.raises(RouteError, match="puts it in DF1"):
        _accept(tmp_path, clock, title=_readers(route_darkness.vault_title(2, True)))


@pytest.mark.parametrize(("name", "command", "expected"), [
    ("darkness-vault", "accept", "save"), ("darkness", "measure", "save"),
    ("darkness-reload", "measure", "reload")])
def test_the_cli_runs_a_spare_manifest_on_its_spare_route(
        tmp_path, monkeypatch, name, command, expected):
    called = []
    monkeypatch.setattr(acceptance, "run_recon", lambda path, **kw: called.append(kw) or {
        "success": True, "error": "", "fetched": {}})
    monkeypatch.setattr(acceptance, "WinGuest", lambda: object())
    monkeypatch.setattr(acceptance, "PixelGuards", lambda path: ("guards", str(path)))
    monkeypatch.setattr(acceptance, "_summary", lambda *a: "")
    manifest = tmp_path / "prepare.json"
    manifest.write_text(json.dumps({
        "vault": {"items": 2, "coins": [0, 0, 1]}, SPARE: {"path": "m.adf"},
        "loaded_letter": "G", "spare_vault": {"items": 3, "coins": [0, 0, 0]}}))
    extra = ["--identity", "i.json"] if command == "accept" else []
    assert acceptance.main([command, "--title", name, "--manifest", str(manifest),
                            "--audio-proof", str(tmp_path / "mute.json"), "--attempt", "a1",
                            "--guards", "g.json", *extra]) == 0
    title = called[0]["title"]
    if expected == "save":
        base = route_darkness.vault_title(2, True) if name == "darkness-vault" else (
            route_darkness.DARKNESS)
        assert title == route_darkness.spare_save_title(base)
    else:
        assert title == route_darkness.spare_reload_title("G", 3, False)


@pytest.mark.parametrize("command", ["accept", "reload"])
def test_a_spare_reload_runs_only_as_measure(tmp_path, monkeypatch, command):
    monkeypatch.setattr(acceptance, "run_recon", lambda *a, **kw: pytest.fail("ran"))
    manifest = tmp_path / "prepare.json"
    manifest.write_text(json.dumps({SPARE: {}, "loaded_letter": "G",
                                    "spare_vault": {"items": 1, "coins": [0, 0, 0]}}))
    assert acceptance.main([command, "--title", "darkness-reload", "--manifest", str(manifest),
                            "--audio-proof", str(tmp_path / "m.json"), "--attempt", "a1",
                            "--guards", "g.json", "--identity", "i.json"]) == 2


# The reload from the spare.

def _accepted(tmp_path, *, success=True, saves=("G",)):
    """The disk 3, spare and summary a spare accept run would have fetched."""
    disk3 = tmp_path / "fetched-disk3.adf"
    spare = tmp_path / "fetched-spare.adf"
    disk3.write_bytes(_disk("POD 3", [("B", _slot())], _empty_vaults()).to_bytes())
    spare.write_bytes(_disk("Empty", [(c, _slot()) for c in saves],
                            {**_empty_vaults(), "G": HELD_BYTES}).to_bytes())
    sha = {key: hashlib.sha256(path.read_bytes()).hexdigest()
           for key, path in (("disk3", disk3), (SPARE, spare))}
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"success": success, "accept": True, "fetched": {
        key: {"sha256": value} for key, value in sha.items()}}))
    return disk3, sha["disk3"], summary, spare


@pytest.fixture
def reload_pinned(pinned, monkeypatch):
    monkeypatch.setattr(route_darkness, "_darkness_slot_letters", _letters)
    return pinned


def test_a_spare_reload_prepares_the_one_slot_on_the_spare_and_its_vault(reload_pinned):
    disk3, sha, summary, spare = _accepted(reload_pinned)
    manifest = route_darkness._prepare_darkness_spare_reload(
        reload_pinned / "run", disk3, sha, summary, spare)
    assert manifest["loaded_letter"] == "G" and manifest["title"] == "darkness-reload"
    assert manifest["spare_vault"]["items"] == 2 and manifest["spare_vault"]["coins"] == [
        1750, 495, 82]
    assert set(manifest["disks"]) == {"disk1", "disk2", "disk3", SPARE}
    assert (reload_pinned / "run" / "spare.adf").read_bytes() == spare.read_bytes()
    assert manifest["registered"]["accept_spare"]["path"] == str(spare)
    json.dumps(manifest)


@pytest.mark.parametrize("spoil", ["failed", "two saves", "other spare", "other disk 3"])
def test_a_spare_reload_blocks_an_accept_run_it_cannot_trust(reload_pinned, spoil):
    disk3, sha, summary, spare = _accepted(
        reload_pinned, success=spoil != "failed",
        saves=("F", "G") if spoil == "two saves" else ("G",))
    if spoil == "other spare":
        spare.write_bytes(_disk("Empty", [("G", _slot())], _empty_vaults()).to_bytes())
    if spoil == "other disk 3":
        sha = "0" * 64
    with pytest.raises(RouteError):
        route_darkness._prepare_darkness_spare_reload(
            reload_pinned / "run", disk3, sha, summary, spare)
    assert not (reload_pinned / "run").exists()


def test_prepare_sends_a_reload_with_a_spare_to_the_spare_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    seen = []

    def fake(run, *args):
        seen.append(args)
        scratch.ensure(run)
        return {"title": "darkness-reload", "names_a": NAMES}

    monkeypatch.setattr(acceptance, "_prepare_darkness_spare_reload", fake)
    acceptance.prepare(acceptance.DARKNESS_RELOAD, "r", specimen=tmp_path / "d3",
                       specimen_sha256="ab", accept_summary=tmp_path / "s.json",
                       spare=tmp_path / "sp")
    assert seen == [(tmp_path / "d3", "ab", tmp_path / "s.json", tmp_path / "sp")]


def test_the_spare_reload_measures_its_route_and_writes_nothing(tmp_path, clock):
    disks = {"disk1": _entry(tmp_path / "disk1.adf", _disk("POD 1")),
             "disk2": _entry(tmp_path / "disk2.adf", _disk("POD 2")),
             "disk3": _entry(tmp_path / "disk3.adf", _disk("POD 3", (), _empty_vaults())),
             SPARE: _entry(tmp_path / "spare.adf", _disk("Empty", [("G", _slot(DARK_START))],
                                                         _empty_vaults()))}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps({
        "disks": disks, "registered": {}, "loaded_letter": "G", "state_a": DARK_START,
        "names_a": NAMES, SPARE: {"path": "x", "sha256": disks[SPARE]["sha256"]},
        "spare_vault": {"items": 2, "coins": [0, 0, 0], "sha256": None}}))
    title = _readers(route_darkness.spare_reload_title("G", 2, False))
    guest = DriveGuest(clock, loaded="G", writes=())
    result = acceptance.run_recon(
        path, guest=guest, guard=MapGuard(states=tuple({s for _, s, _ in title.route})),
        holder="wish679-test", audio_proof=_audio_proof(tmp_path), title=title, measure=True)
    assert result["error"] == "" and result["success"] is True
    assert result["control_sha256"] is None and "fetched_save_error" not in result
    assert result["disks_unchanged"] == {key: True for key in ("disk1", "disk2", "disk3", SPARE)}
    assert _keys(guest) == [
        "P", ("insert", 1, "spare.adf"), "L", "P", "G", ("insert", 1, "disk3.adf"), "SPACE",
        ("insert", 0, "disk2.adf"), "SPACE", "V", "E", "B", "X", "RET", "S", "T", "NP2", "E", "E"]
    assert guest.bad_hash == [] and all(result["disks_unchanged"].values())


# The disk 3 the run hashes again before it goes back into DF1.

def _insert_errors(result):
    return [e for e in result["events"] if "insert" in e and "error" in e]


@pytest.mark.parametrize("damage", ["volume", "file", "unverified"])
def test_a_fetched_disk_3_that_is_not_the_staged_disk_is_not_put_back(tmp_path, clock, damage):
    class Swapped(DriveGuest):
        def get(self, remote, local, timeout=None):
            super().get(remote, local, timeout)
            if remote.endswith("-disk3.adf"):
                disk = AmigaDisk(local.read_bytes())
                if damage == "volume":
                    other = _disk("OTHER", (), {})
                    local.write_bytes(other.to_bytes())
                elif damage == "file":
                    disk.remove_file("/SAVE/savgamA.sav")
                    local.write_bytes(disk.to_bytes())
                else:
                    local.write_bytes(b"\0" * len(local.read_bytes()))

    guest, result = _accept(tmp_path, clock, guest=Swapped(clock))
    assert result["success"] is False
    errors = _insert_errors(result)
    assert [e["insert"] for e in errors] == ["disk3"]
    assert not any("rehashed" in e for e in result["events"])


def test_a_failed_fetch_before_the_reinsert_is_logged_as_an_insert_error(tmp_path, clock):
    class NoFetch(DriveGuest):
        def get(self, remote, local, timeout=None):
            if remote.endswith("-disk3.adf") and any(c[0] == "insert" for c in self.calls):
                raise OSError("no such file on the guest")
            super().get(remote, local, timeout)

    _, result = _accept(tmp_path, clock, guest=NoFetch(clock))
    assert result["success"] is False
    assert [e["insert"] for e in _insert_errors(result)] == ["disk3"]


def test_only_disk_3_and_the_spare_are_hashed_again(tmp_path, clock):
    guest, result = _accept(tmp_path, clock)
    assert {e["rehashed"] for e in result["events"] if "rehashed" in e} <= {"disk3", SPARE}


# The route and the spare source.

def test_a_quit_answer_that_does_not_follow_exit_game_stops_the_spare_route():
    title = _readers(route_darkness.vault_title(2, True))
    route = tuple(("P", "party_menu", "key") if step == route_darkness._QUIT_NO else step
                  for step in title.route)
    bare = dataclasses.replace(title, route=(*route, route_darkness._QUIT_NO))
    with pytest.raises(RouteError, match="exit_game"):
        route_darkness.spare_save_title(bare)


def test_a_spare_with_a_vault_that_holds_items_is_not_blank(pinned):
    spare = pinned / "full.adf"
    _disk("Empty", (), {**_empty_vaults(), "A": HELD_BYTES}).save(spare)
    with pytest.raises(RouteError, match="not blank"):
        route_darkness._prepare_darkness(pinned / "run", None, "B", spare=spare)


def test_a_spare_source_that_changes_during_preparation_stops_the_run(pinned, monkeypatch):
    spare = pinned / "minimal.adf"
    _disk("Empty", (), _empty_vaults()).save(spare)
    real = route_darkness._find_images
    calls = []

    def touching(wanted):
        calls.append(1)
        if len(calls) == 2:
            spare.write_bytes(spare.read_bytes() + b"x")
        return real(wanted)

    monkeypatch.setattr(route_darkness, "_find_images", touching)
    with pytest.raises(RouteError, match="source spare"):
        route_darkness._prepare_darkness(pinned / "run", None, "B", spare=spare)


# Seeding the spare's loaded-letter vault.

THREE = dos_codec.PodVault(10, 20, 30, tuple(bytes([n]) + bytes(62) for n in (1, 2, 3)))


def _stage_vault(pinned, monkeypatch, vault):
    """`pinned` with `vault`, the bytes of Vault B, staged on disk 3; returns the blank spare."""
    disk3 = _disk(route_darkness.DARKNESS_VOLUME, (), {"B": vault})
    images = {"disk1": ("d1", b"one"), "disk2": ("d2", b"two"), "disk3": ("d3", disk3.to_bytes())}
    monkeypatch.setattr(route_darkness, "DARKNESS_DISK3_SHA256",
                        hashlib.sha256(images["disk3"][1]).hexdigest())
    monkeypatch.setattr(route_darkness, "_find_images",
                        lambda wanted: {k: images[k] for k in wanted})
    spare = pinned / "minimal.adf"
    _disk("Empty", (), _empty_vaults()).save(spare)
    return pinned, spare


@pytest.fixture
def vault_pinned(pinned, monkeypatch):
    """`pinned` with three rows staged in disk 3's vault B."""
    return _stage_vault(pinned, monkeypatch, amiga_savegame.pod_vault_to_amiga(THREE))


def _scroll_case_vault():
    """Three rows as the game writes them: a plain item, a scroll case with two chained nodes, a plain item.

    The padding after the nodes is a pattern rather than zeros, standing for the game's template.
    """
    node = amiga_savegame.POD_ITEM_BYTES
    plain = amiga_savegame.pod_vault_to_amiga(THREE)[16:16 + 3 * node]
    one, two, three = (plain[i * node:(i + 1) * node] for i in range(3))
    scroll = bytearray(two)
    at = amiga_pod.ITEM_FIELD_AT
    scroll[at["type_index"]] = amiga_pod.SCROLL_TYPE_INDEX
    scroll[at["quantity"]:at["quantity"] + 2] = (2).to_bytes(2, "big")
    nodes = one + bytes(scroll) + two + three + three
    body = bytes(12) + b"\xff\xff" + (3).to_bytes(2, "big") + nodes
    template = bytes(range(1, 256)) * 30
    return body + template[:amiga_savegame.POD_VAULT_SIZE - len(body)], len(body)


def test_a_seed_ending_on_a_scroll_case_keeps_its_chained_nodes_and_the_files_own_padding(
        pinned, monkeypatch):
    vault, end = _scroll_case_vault()
    pinned, spare = _stage_vault(pinned, monkeypatch, vault)
    route_darkness._prepare_darkness(
        pinned / "run", None, "B", vault=True, spare=spare, spare_seed_rows=2)
    seeded = AmigaDisk.open(pinned / "run" / "spare.adf").read_file("/SAVE/VaultB.DAT")
    assert len(seeded) == len(vault)
    assert seeded[:12] == bytes(12) and seeded[12:14] == b"\xff\xff"
    assert seeded[14:16] == (2).to_bytes(2, "big")
    kept_end = 16 + 4 * amiga_savegame.POD_ITEM_BYTES
    assert seeded[16:kept_end] == vault[16:kept_end]
    assert seeded[kept_end:kept_end + len(vault) - end] == vault[end:]


@pytest.mark.parametrize("rows", [0, 3])
def test_a_seed_is_bounded_by_the_files_own_rows_not_its_decoded_items(
        pinned, monkeypatch, rows):
    vault, _end = _scroll_case_vault()
    pinned, spare = _stage_vault(pinned, monkeypatch, vault)
    with pytest.raises(RouteError, match="spare seed"):
        route_darkness._prepare_darkness(
            pinned / "run", None, "B", vault=True, spare=spare, spare_seed_rows=rows)


def test_a_seeded_spare_holds_the_first_rows_of_the_staged_vault_and_the_source_is_unchanged(
        vault_pinned):
    pinned, spare = vault_pinned
    before = spare.read_bytes()
    manifest = route_darkness._prepare_darkness(
        pinned / "run", None, "B", vault=True, spare=spare, spare_seed_rows=2)
    working = AmigaDisk.open(pinned / "run" / "spare.adf")
    seeded = amiga_savegame.pod_read_vault(working, "B")
    staged = amiga_savegame.pod_read_vault(AmigaDisk(AmigaDisk.open(
        pinned / "run" / "disk3.adf").to_bytes()), "B")
    assert len(staged.items) == 3
    assert seeded.items == staged.items[:2] and seeded != dos_codec.EMPTY_POD_VAULT
    assert spare.read_bytes() == before
    assert amiga_savegame.pod_read_vault(AmigaDisk.open(spare), "B") == dos_codec.EMPTY_POD_VAULT
    working_hash = hashlib.sha256((pinned / "run" / "spare.adf").read_bytes()).hexdigest()
    assert manifest["disks"][SPARE]["sha256"] == working_hash != manifest[SPARE]["sha256"]
    assert manifest[SPARE]["sha256"] == hashlib.sha256(before).hexdigest()
    assert manifest["spare_seed"]["letter"] == "B" and manifest["spare_seed"]["items"] == 2
    assert manifest["spare_seed"]["coins"] == [0, 0, 0]
    json.dumps(manifest)


def test_a_spare_without_a_seed_still_has_to_be_blank_and_records_no_seed(vault_pinned):
    pinned, spare = vault_pinned
    manifest = route_darkness._prepare_darkness(pinned / "run", None, "B", vault=True, spare=spare)
    assert "spare_seed" not in manifest
    assert manifest["disks"][SPARE]["sha256"] == manifest[SPARE]["sha256"]
    full = pinned / "full.adf"
    _disk("Empty", (), {**_empty_vaults(), "B": amiga_savegame.pod_vault_to_amiga(THREE)}).save(full)
    with pytest.raises(RouteError, match="not blank"):
        route_darkness._prepare_darkness(pinned / "run2", None, "B", vault=True, spare=full)
    with pytest.raises(RouteError, match="not blank"):
        route_darkness._prepare_darkness(pinned / "run3", None, "B", vault=True, spare=full,
                                         spare_seed_rows=1)


@pytest.mark.parametrize("rows", [0, -1, 3, 4])
def test_a_seed_of_no_rows_or_all_the_staged_rows_writes_no_run(vault_pinned, rows):
    pinned, spare = vault_pinned
    with pytest.raises(RouteError, match="spare seed"):
        route_darkness._prepare_darkness(
            pinned / "run", None, "B", vault=True, spare=spare, spare_seed_rows=rows)
    assert not (pinned / "run").exists()


def test_a_seed_needs_a_vault_title_and_a_spare(vault_pinned):
    pinned, spare = vault_pinned
    with pytest.raises(RouteError, match="spare seed"):
        route_darkness._prepare_darkness(pinned / "run", None, "B", spare=spare, spare_seed_rows=1)
    with pytest.raises(RouteError, match="spare seed"):
        route_darkness._prepare_darkness(pinned / "run2", None, "B", vault=True,
                                         spare_seed_rows=1)
    assert not (pinned / "run").exists() and not (pinned / "run2").exists()


def test_prepare_passes_the_seed_only_to_darkness_vault_with_a_spare(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    seen = []

    def fake(run, specimen, **kw):
        seen.append(kw)
        scratch.ensure(run)
        return {"title": "darkness", "names_a": NAMES}

    monkeypatch.setattr(acceptance, "_PREPARE", {"darkness-vault": fake, "darkness": fake})
    spare = tmp_path / "s.adf"
    acceptance.prepare(acceptance.DARKNESS_VAULT, "r1", spare=spare, spare_seed_rows=2)
    assert seen == [{"substitute": None, "substitute_letter": "A", "spare": spare,
                     "spare_seed_rows": 2}]
    with pytest.raises(RouteError, match="--spare-seed-rows is for"):
        acceptance.prepare(acceptance.DARKNESS, "r2", spare=spare, spare_seed_rows=2)
    with pytest.raises(RouteError, match="--spare-seed-rows is for"):
        acceptance.prepare(acceptance.DARKNESS_VAULT, "r3", spare_seed_rows=2)
    assert len(seen) == 1


def test_the_cli_hands_the_seed_rows_to_prepare_and_blocks_them_on_a_published_disk(
        tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(acceptance, "prepare",
                        lambda title, run_id, **kw: seen.append(kw) or tmp_path / "p.json")
    assert acceptance.main(["prepare", "--title", "darkness-vault", "--run-id", "r",
                            "--spare-disk", "m.adf", "--spare-seed-rows", "3"]) == 0
    assert seen[0]["spare_seed_rows"] == 3
    assert acceptance.main(["prepare", "--title", "darkness-vault", "--run-id", "r",
                            "--spare-disk", "m.adf"]) == 0
    assert "spare_seed_rows" not in seen[1]
    assert acceptance.main(["prepare", "--title", "darkness", "--run-id", "r",
                            "--published-disk-three", "--saveas-report", "r.json",
                            "--spare-seed-rows", "3"]) == 2
    assert len(seen) == 2


def test_spare_matches_seed_is_recorded_only_for_a_seeded_run():
    staged = _disk("Disk3", (), {"B": HELD_BYTES})
    spare = _disk("Spare", (), {"G": amiga_savegame.pod_vault_to_amiga(THREE)})
    disk3 = _disk("Disk3", (), {})
    seed = dos_codec.PodVault(0, 0, 0, THREE.items)
    found = acceptance._spare_vault(disk3, spare, staged, "B", "F", "G", seed)
    assert found["spare_matches_seed"] is False  # THREE carries coins the seed lacks
    seed = amiga_savegame.pod_read_vault(spare, "G")
    assert acceptance._spare_vault(disk3, spare, staged, "B", "F", "G", seed)[
        "spare_matches_seed"] is True
    assert "spare_matches_seed" not in acceptance._spare_vault(disk3, spare, staged, "B", "F", "G")
