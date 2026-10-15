"""`tools/convert/convertrun.py` and `tools/convert/saveasdrive.py` publish through
Save As, so what the emulator boots is what the editor's Save As writes.

Both tests need a DOS save and the player's own C64 disks and skip cleanly
without either.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from conftest import load_tools_module
from gamedata import curse_absent, curse_dir, disk_dir
from support.dossave import _game_dirs, _save_dir, needs_dos_saves

from editor import saveplan
from editor.convert import Source
from editor.roster import Party

convertrun = load_tools_module("convertrun")

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")
needs_curse_disks = pytest.mark.skipif(curse_absent(),
                                       reason="needs Curse's game disks")


@needs_dos_saves
@needs_disks
def test_a_c64_conversion_is_the_output_of_save_as(tmp_path, monkeypatch):
    """The `.d64` written is the exact bytes `prepare_save_as` produced, and
    `publish` is what put it down."""
    prepared = []
    real = saveplan.prepare_save_as

    def spy(*args, **kwargs):
        plan = real(*args, **kwargs)
        prepared.append(plan)
        return plan

    monkeypatch.setattr(saveplan, "prepare_save_as", spy)
    out = tmp_path / "out"
    out.mkdir()

    report = convertrun.write_via_save_as(_save_dir() / "SAVGAMA.DAT", "c64",
                                          out, None, disk_dir())

    assert "stopped" not in report
    assert len(prepared) == 1
    (written,) = [p for p in report["written"] if p.endswith(".D64")]
    (data,) = prepared[0].files.values()
    assert open(written, "rb").read() == data


@needs_curse_disks
def test_a_non_default_source_slot_converts_that_slots_party(tmp_path):
    """`--source-slot` reaches a multi-slot DOS source: the archives' Curse
    `Default files/Saves` holds A and B, and the C64 disk written for B holds
    B's party, not A's default."""
    folder = _game_dirs().get("CURSE")
    if folder is None:
        pytest.skip("needs the archives' Curse Default files/Saves")
    b_names = [m.name for m in Party(Source.detect(folder, slot="B")).members]
    assert b_names  # slot B exists and is not slot A's party
    a_names = [m.name for m in Party(Source.detect(folder, slot="A")).members]
    assert b_names != a_names

    out = tmp_path / "out"
    out.mkdir()
    report = convertrun.write_via_save_as(folder, "c64", out, None,
                                          curse_dir(), source_slot="B")

    assert "stopped" not in report
    (written,) = [p for p in report["written"] if p.endswith(".D64")]
    landed = [m.name for m in
              Party(Source.detect(pathlib.Path(written))).members]
    assert landed == b_names


@needs_dos_saves
@needs_disks
def test_a_blocked_save_as_writes_nothing_and_says_why(tmp_path, monkeypatch):
    """A conversion Save As blocks is reported under `stopped`, and nothing
    lands under the output folder."""
    def block(*args, **kwargs):
        raise saveplan.DroppedFields(["a field the writer cannot hold"])

    monkeypatch.setattr(saveplan, "prepare_save_as", block)
    out = tmp_path / "out"
    out.mkdir()

    report = convertrun.write_via_save_as(_save_dir() / "SAVGAMA.DAT", "c64",
                                          out, None, disk_dir())

    assert report["stopped"][0] == "DroppedFields"
    assert "written" not in report
    assert list(out.glob("wish-*")) == []


def test_leave_chooses_the_item_an_over_limit_pack_leaves_behind(
        tmp_path, monkeypatch):
    """A pack needing 17 C64 slots is blocked without `leave` and converts
    with it, the chosen item recorded as left behind."""
    from support.silverblades import ssb_dir
    from test_leavechoice import NO_LEAVE_MESSAGE, _crowded_folder

    disks = ssb_dir()
    if disks is None:
        pytest.skip("needs the Silver Blades disks")
    prepared = []
    real = saveplan.prepare_save_as

    def spy(*args, **kwargs):
        plan = real(*args, **kwargs)
        prepared.append(plan)
        return plan

    monkeypatch.setattr(saveplan, "prepare_save_as", spy)
    folder = _crowded_folder(tmp_path)
    out = tmp_path / "out"
    out.mkdir()

    blocked = convertrun.write_via_save_as(folder, "c64", out, None, disks,
                                           source_slot="A")
    assert blocked["stopped"][0] == "JoinedScrollsDoNotFit", blocked
    assert NO_LEAVE_MESSAGE in blocked["stopped"][1]
    assert "written" not in blocked

    report = convertrun.write_via_save_as(folder, "c64", out, None, disks,
                                          source_slot="A", leave={0: {3}})
    assert "stopped" not in report, report
    assert report["written"]
    (left,) = prepared[0].report.left_behind
    assert "left behind" in left
    assert report["left_behind"] == list(prepared[-1].report.left_behind)



# ---------------------------------------------------------------------------
# Which DOS game folder `--to dos` writes against
# ---------------------------------------------------------------------------

POOL = "pool-of-radiance"
SILVER = "secret-of-the-silver-blades"
DARKNESS = "pools-of-darkness"

#: Launcher stem -> what the fake folder holds: launcher and configuration.
HOLDS = {"POOLRAD": ("START.EXE", "POOL.CFG"),
         "CURSE": ("START.EXE", "CURSE.CFG"),
         "SECRET": ("START.EXE", "BLADES.CFG"),
         "DARKNESS": ("START.BAT", "POOL4.CFG")}


def _game_folder(where, stem, lower=False):
    """An empty stand-in for a DOS game folder holding `stem`'s files."""
    where.mkdir(parents=True)
    for name in HOLDS[stem]:
        (where / (name.lower() if lower else name)).write_bytes(b"")
    return where


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """`convertrun.main` with the archives, the source and Save As faked:
    each title's folder holds its launcher and configuration file, and the
    Save As stand-in records what it was given and writes nothing."""
    from tools.dos import dospod

    archives = {stem: _game_folder(tmp_path / "archives" / stem, stem)
                for stem in HOLDS}
    calls = []
    detected = []

    def find_game(stem="POOLRAD"):
        return archives[stem]

    def save_as(source, to, folder, game, disks, **kwargs):
        calls.append(game)
        return {"written": [], "stopped": ["Fake", "nothing written"]}

    title = {}

    class FakeSource:
        @classmethod
        def detect(cls, path, party=None, slot=None):
            detected.append(path)
            if title["key"] is None:
                raise ValueError("not a save")
            return type("Detected", (), {"key": title["key"]})()

    import editor.convert
    monkeypatch.setattr(convertrun.dosbox, "find_game", find_game)
    monkeypatch.setattr(dospod, "find_game", find_game)
    monkeypatch.setattr(convertrun, "write_via_save_as", save_as)
    monkeypatch.setattr(convertrun, "disks_dir", lambda named=None: tmp_path)
    monkeypatch.setattr(editor.convert, "Source", FakeSource)
    out = tmp_path / "out"

    def run(key, *extra, to="dos"):
        title["key"] = key
        argv = ["--source", str(tmp_path / "SOURCE.D64"), "--to", to,
                "--out", str(out), "--no-play", *extra]
        return convertrun.main(argv)

    run.archives, run.calls, run.out, run.detected = (
        archives, calls, out, detected)
    run.tmp = tmp_path
    return run


def _stops(run, key, *extra):
    """The sentence a stopped run printed, having written nothing."""
    with pytest.raises(SystemExit) as stopped:
        run(key, *extra)
    assert run.calls == []
    assert not run.out.exists()
    return str(stopped.value)


def test_a_silver_blades_source_is_written_against_silver_blades(fake_run):
    """No `--game`: a Silver Blades save is written against the Silver
    Blades folder, not Pool of Radiance's."""
    fake_run(SILVER)
    assert fake_run.calls == [fake_run.archives["SECRET"]]


@pytest.mark.parametrize("key, stem", [(SILVER, "POOLRAD"),
                                       (POOL, "SECRET"),
                                       (DARKNESS, "POOLRAD")])
def test_a_game_folder_of_another_title_stops_before_writing(
        fake_run, key, stem):
    """A `--game` folder holding another title stops the run with a sentence
    naming both titles, before Save As runs or `--out` is made."""
    message = _stops(fake_run, key, "--game", str(fake_run.archives[stem]))
    assert message.startswith("The DOS game folder ")
    assert "but the save is" in message


def test_another_title_under_an_unrecognised_name_stops(fake_run):
    """What the folder holds decides, whatever it is called."""
    games = _game_folder(fake_run.tmp / "Games", "POOLRAD")
    message = _stops(fake_run, SILVER, "--game", str(games))
    assert message == (f"The DOS game folder {games} is Pool of Radiance, "
                       f"but the save is Secret of the Silver Blades.")


def test_a_folder_holding_no_title_under_no_title_name_stops(fake_run):
    """Nothing in it and nothing in its name: the run cannot tell."""
    empty = fake_run.tmp / "Empty"
    empty.mkdir()
    message = _stops(fake_run, POOL, "--game", str(empty))
    assert message == (f"Cannot tell which game the DOS game folder {empty} "
                       f"holds.")


def test_a_pool_source_is_written_against_pool_as_before(fake_run):
    """A Pool of Radiance save still takes Pool's folder by default, and
    the Pool folder named outright is used as given."""
    fake_run(POOL)
    fake_run(POOL, "--game", str(fake_run.archives["POOLRAD"]))
    assert fake_run.calls == [fake_run.archives["POOLRAD"]] * 2


@pytest.mark.parametrize("name, lower", [("poolrad", True),
                                         ("My Pool copy", False),
                                         ("copy", True)])
def test_a_lowercase_or_renamed_pool_folder_is_recognised(
        fake_run, name, lower):
    """A copy of the game under another name, or with its files in lower
    case, is recognised by what it holds and used as given."""
    copy = _game_folder(fake_run.tmp / name, "POOLRAD", lower=lower)
    fake_run(POOL, "--game", str(copy))
    assert fake_run.calls == [copy]


def test_a_folder_named_for_its_title_is_recognised_by_name(fake_run):
    """A folder named `POOLRAD` with no configuration file in it still
    counts as Pool of Radiance's."""
    bare = fake_run.tmp / "bare" / "POOLRAD"
    bare.mkdir(parents=True)
    fake_run(POOL, "--game", str(bare))
    assert fake_run.calls == [bare]


def test_a_symlinked_folder_is_used_as_given(fake_run):
    """A link to the right folder, under a name of its own, is accepted
    and handed on as the link."""
    link = fake_run.tmp / "linked"
    try:
        link.symlink_to(fake_run.archives["SECRET"], target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this filesystem makes no symbolic links")
    fake_run(SILVER, "--game", str(link))
    assert fake_run.calls == [link]


def test_a_trailing_slash_is_the_same_folder(fake_run):
    folder = fake_run.archives["SECRET"]
    fake_run(SILVER, "--game", str(folder) + "/")
    assert fake_run.calls == [folder]


def test_a_pools_of_darkness_source_is_written_against_darkness(fake_run):
    fake_run(DARKNESS)
    assert fake_run.calls == [fake_run.archives["DARKNESS"]]


def test_a_source_nothing_can_open_keeps_the_old_default(fake_run):
    """An unopenable source keeps Pool's folder, or the one named, and
    Save As says why it fails."""
    fake_run(None)
    fake_run(None, "--game", str(fake_run.archives["SECRET"]))
    assert fake_run.calls == [fake_run.archives["POOLRAD"],
                              fake_run.archives["SECRET"]]


def test_a_c64_destination_ignores_the_game_folder(fake_run):
    """`--to c64` neither opens the source early nor checks `--game`."""
    fake_run(SILVER, to="c64")
    fake_run(SILVER, "--game", str(fake_run.archives["POOLRAD"]), to="c64")
    assert fake_run.calls == [None, fake_run.archives["POOLRAD"]]
    assert fake_run.detected == []


def test_missing_archives_stop_before_writing(fake_run, monkeypatch):
    def nowhere(stem="POOLRAD"):
        raise FileNotFoundError(f"no DOS {stem}")

    monkeypatch.setattr(convertrun.dosbox, "find_game", nowhere)
    message = _stops(fake_run, SILVER)
    assert message == ("No DOS Secret of the Silver Blades game folder was "
                       "found.")


# ---------------------------------------------------------------------------
# The C64 walk: the encounter switch, and a walk that never moved
# ---------------------------------------------------------------------------

def _fake_savecheck(monkeypatch, walks, title="pool-of-radiance"):
    """`play_c64` against a `savecheck.py` that only writes `walks` to its log
    and records the command it was given."""
    import json
    import subprocess
    argvs = []

    def run(argv, **kw):
        argvs.append(argv)
        log = pathlib.Path(argv[argv.index("--out") + 1])
        log.write_text("".join(json.dumps({"kind": "walk", "moved": m}) + "\n"
                               for m in walks))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(convertrun.subprocess, "run", run)
    monkeypatch.setattr(convertrun, "c64_title", lambda disk: title)
    return argvs


def test_no_encounters_reaches_savecheck(tmp_path, monkeypatch):
    argvs = _fake_savecheck(monkeypatch, [True])
    played = convertrun.play_c64(tmp_path / "W.D64", tmp_path, tmp_path,
                                 "II", True, "r.D64", no_encounters=True)
    assert "--no-encounters" in argvs[0]
    assert played["moved"] is True


def test_without_the_switch_savecheck_meets_encounters(tmp_path, monkeypatch):
    argvs = _fake_savecheck(monkeypatch, [True])
    convertrun.play_c64(tmp_path / "W.D64", tmp_path, tmp_path, "II", True,
                        None)
    assert "--no-encounters" not in argvs[0]


def test_a_curse_disk_is_not_booted_with_the_switch(tmp_path, monkeypatch):
    argvs = _fake_savecheck(monkeypatch, [True],
                            title="curse-of-the-azure-bonds")
    played = convertrun.play_c64(tmp_path / "W.D64", tmp_path, tmp_path,
                                 "II", True, None, no_encounters=True)
    assert argvs == []
    assert played["returncode"] != 0


def test_a_c64_walk_that_never_moved_fails_the_run(tmp_path, monkeypatch):
    """A run whose every walked move reads `moved: false` returns 1; one
    move that moved is enough for 0."""
    _fake_savecheck(monkeypatch, [False, False])
    disk = tmp_path / "WISHSAVE.D64"
    disk.write_bytes(b"")
    monkeypatch.setattr(convertrun, "disks_dir", lambda named=None: tmp_path)
    monkeypatch.setattr(convertrun, "write_via_save_as",
                        lambda *a, **k: {"written": [str(disk)]})
    argv = ["--source", str(tmp_path / "S.adf"), "--to", "c64",
            "--out", str(tmp_path / "out"), "--walk", "II"]
    assert convertrun.main(argv) == 1
    _fake_savecheck(monkeypatch, [False, True])
    assert convertrun.main(argv) == 0


def test_no_encounters_is_blocked_for_a_dos_destination(tmp_path):
    with pytest.raises(SystemExit):
        convertrun.main(["--source", str(tmp_path / "S.D64"), "--to", "dos",
                         "--out", str(tmp_path / "out"), "--no-encounters"])
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# An Amiga destination
# ---------------------------------------------------------------------------

def _digests(source: pathlib.Path, disk: pathlib.Path) -> dict:
    """SHA-256 of the disk and of every file in the source save."""
    import hashlib
    files = [disk, *sorted(p for p in source.rglob("*") if p.is_file())]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files}


@needs_disks
def test_an_amiga_destination_is_written_by_the_editors_save_as(
        tmp_path, monkeypatch):
    """`--to amiga` goes through `prepare_save_as` and `publish` with the
    named disk 2, and the slot it writes reads back as an Amiga Pool of
    Radiance party."""
    import gamedata
    from support.toamigapor import _por_disk_2

    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

    root = gamedata.specimen_root()
    source = (root / "por-dos" / "WISH-SPEC-por-item-granted"
              if root else None)
    if source is None or not source.is_dir():
        pytest.skip("needs the specimen WISH-SPEC-por-item-granted")
    disk = _por_disk_2(tmp_path)
    called = []
    real_prepare, real_publish = saveplan.prepare_save_as, saveplan.publish

    def prepare(*args, **kwargs):
        called.append("prepare_save_as")
        return real_prepare(*args, **kwargs)

    def publish(*args, **kwargs):
        called.append("publish")
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(saveplan, "prepare_save_as", prepare)
    monkeypatch.setattr(saveplan, "publish", publish)
    out = tmp_path / "out"
    digest = _digests(source, disk)

    rc = convertrun.main(["--source", str(source), "--source-slot", "D",
                          "--to", "amiga", "--amiga-disk", str(disk),
                          "--out", str(out)])

    assert rc == 0
    assert called == ["prepare_save_as", "publish"]
    written = [p for p in out.rglob("*.ADF")]
    assert len(written) == 1
    assert written[0].resolve() != disk.resolve()
    assert _digests(source, disk) == digest
    party, _save = amiga_savegame.read_por_slot(
        AmigaDisk.open(str(written[0])), "D")
    assert party


def _no_write(monkeypatch):
    """Stand in for `write_via_save_as`, recording whether it ran."""
    ran = []

    def fake(*args, **kwargs):
        ran.append((args, kwargs))
        return {"written": []}

    monkeypatch.setattr(convertrun, "write_via_save_as", fake)
    return ran


def test_an_amiga_destination_needs_a_disk_2(tmp_path, monkeypatch, capsys):
    ran = _no_write(monkeypatch)
    with pytest.raises(SystemExit):
        convertrun.main(["--source", str(tmp_path / "S"), "--to", "amiga",
                         "--out", str(tmp_path / "out")])
    assert "--to amiga needs --amiga-disk" in capsys.readouterr().err
    assert not ran
    assert not (tmp_path / "out").exists()


def test_a_missing_amiga_disk_stops_naming_its_path(
        tmp_path, monkeypatch, capsys):
    ran = _no_write(monkeypatch)
    gone = tmp_path / "gone.adf"
    with pytest.raises(SystemExit):
        convertrun.main(["--source", str(tmp_path / "S"), "--to", "amiga",
                         "--amiga-disk", str(gone),
                         "--out", str(tmp_path / "out")])
    assert f"There is no Amiga disk at {gone}." in capsys.readouterr().err
    assert not ran
    assert not (tmp_path / "out").exists()


def test_an_amiga_destination_needs_no_c64_disks(tmp_path, monkeypatch):
    ran = _no_write(monkeypatch)
    monkeypatch.setattr(convertrun, "disks_dir", lambda named=None: None)
    disk = tmp_path / "por2.adf"
    disk.write_bytes(b"x")

    rc = convertrun.main(["--source", str(tmp_path / "S"), "--to", "amiga",
                          "--amiga-disk", str(disk),
                          "--out", str(tmp_path / "out")])

    assert rc == 1
    ((args, _kwargs),) = ran
    assert args[4] is None


def test_amiga_disk_one_reaches_save_as(tmp_path, monkeypatch):
    ran = _no_write(monkeypatch)
    monkeypatch.setattr(convertrun, "disks_dir", lambda named=None: None)
    two, one = tmp_path / "curse2.adf", tmp_path / "curse1.adf"
    two.write_bytes(b"x")
    one.write_bytes(b"y")

    rc = convertrun.main(["--source", str(tmp_path / "S"), "--to", "amiga",
                          "--amiga-disk", str(two), "--amiga-disk-one", str(one),
                          "--out", str(tmp_path / "out")])

    assert rc == 1
    ((_args, kwargs),) = ran
    assert kwargs["amiga_disk"] == two
    assert kwargs["amiga_disk_one"] == one
    assert kwargs["amiga_disk_three"] is None


def test_amiga_disk_three_reaches_save_as(tmp_path, monkeypatch):
    ran = _no_write(monkeypatch)
    monkeypatch.setattr(convertrun, "disks_dir", lambda named=None: None)
    two, three = tmp_path / "pod2.adf", tmp_path / "pod3.adf"
    two.write_bytes(b"x")
    three.write_bytes(b"z")

    convertrun.main(["--source", str(tmp_path / "S"), "--to", "amiga",
                     "--amiga-disk", str(two), "--amiga-disk-three", str(three),
                     "--out", str(tmp_path / "out")])

    ((_args, kwargs),) = ran
    assert kwargs["amiga_disk_three"] == three
    assert kwargs["amiga_disk_one"] is None


@pytest.mark.parametrize("option", ["--amiga-disk-one", "--amiga-disk-three"])
def test_a_missing_amiga_disk_one_or_three_stops_naming_its_path(
        tmp_path, monkeypatch, capsys, option):
    ran = _no_write(monkeypatch)
    two, gone = tmp_path / "disk2.adf", tmp_path / "gone.adf"
    two.write_bytes(b"x")
    with pytest.raises(SystemExit):
        convertrun.main(["--source", str(tmp_path / "S"), "--to", "amiga",
                         "--amiga-disk", str(two), option, str(gone),
                         "--out", str(tmp_path / "out")])
    assert f"There is no Amiga disk at {gone}." in capsys.readouterr().err
    assert not ran
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("option", ["--amiga-disk-one", "--amiga-disk-three"])
def test_amiga_disk_one_or_three_is_blocked_for_another_destination(
        tmp_path, monkeypatch, capsys, option):
    ran = _no_write(monkeypatch)
    one = tmp_path / "disk.adf"
    one.write_bytes(b"y")
    with pytest.raises(SystemExit):
        convertrun.main(["--source", str(tmp_path / "S"), "--to", "dos",
                         option, str(one), "--out", str(tmp_path / "out")])
    assert f"{option} is for an Amiga destination" in capsys.readouterr().err
    assert not ran
    assert not (tmp_path / "out").exists()


def test_a_curse_amiga_destination_is_written_onto_a_copy_of_disk_one(
        tmp_path, capsys):
    """A DOS Curse save holding EVOKER, a Pool of Radiance import with a
    permanent strength of 100, goes to the Amiga with the title's disk 1 and
    disk 2 named; the written slot holds him and passes the save checker, and
    neither disk nor the source changes."""
    from gamedata import specimen

    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasavecheck
    from tools.convert import convertdrops

    source = specimen("wish303-s9-curse-evoker-dos-resave", platform="dos")
    key = "curse-of-the-azure-bonds"
    two = convertdrops.amiga_game_disks(tmp_path).get(key)
    one = convertdrops.amiga_disks_one(tmp_path).get(key)
    if two is None or one is None:
        pytest.skip("needs Curse's own Amiga disks 1 and 2")
    digest = {**_digests(source, two), **_digests(source, one)}
    out = tmp_path / "out"

    rc = convertrun.main(["--source", str(source), "--source-slot", "D",
                          "--to", "amiga", "--amiga-disk", str(two),
                          "--amiga-disk-one", str(one), "--out", str(out)])

    assert rc == 0
    written = list(out.rglob("*.ADF"))
    assert len(written) == 1
    assert {**_digests(source, two), **_digests(source, one)} == digest
    slot = json.loads(capsys.readouterr().out)["write"]["slot"]
    save = amiga_savegame.read_slot(AmigaDisk.open(str(written[0])), slot,
                                    amiga_savegame.CURSE)
    names = [c.name for c in save.characters]
    assert "EVOKER" in names
    at = save.blocks[names.index("EVOKER")][0]
    assert save.data[at + 0x10] == 100
    assert [claim for claim, ok, _ in amigasavecheck.check(save)
            if not ok] == []


# ---------------------------------------------------------------------------
# Each title plays through its own driver
# ---------------------------------------------------------------------------

def _record_runs(monkeypatch):
    import subprocess
    argvs = []

    def run(argv, **kw):
        argvs.append([str(a) for a in argv])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(convertrun.subprocess, "run", run)
    return argvs


def test_a_silver_blades_disk_goes_to_the_c64_acceptance_driver(
        tmp_path, monkeypatch):
    argvs = _record_runs(monkeypatch)
    monkeypatch.setattr(convertrun, "c64_title",
                        lambda disk: "secret-of-the-silver-blades")
    played = convertrun.play_c64(tmp_path / "W.D64", tmp_path, tmp_path,
                                 "II", True, None)
    assert len(argvs) == 1
    argv = argvs[0]
    assert pathlib.Path(argv[1]).parts[-3:] == ("tools", "c64", "acceptance.py")
    assert argv[argv.index("--title") + 1] == "ssb"
    assert not any(a.endswith("savecheck.py") for a in argv)
    assert played["returncode"] == 0


def test_a_c64_title_no_driver_plays_stops_before_booting(
        tmp_path, monkeypatch):
    argvs = _record_runs(monkeypatch)
    monkeypatch.setattr(convertrun, "c64_title", lambda disk: "pools-of-darkness")
    played = convertrun.play_c64(tmp_path / "W.D64", tmp_path, tmp_path,
                                 "II", True, None)
    assert argvs == []
    assert played["returncode"] == 2
    assert "pools-of-darkness" in played["error"]


@pytest.mark.parametrize("key, short", [
    ("curse-of-the-azure-bonds", "curse"),
    ("secret-of-the-silver-blades", "ssb"),
])
def test_a_later_dos_title_goes_to_the_dos_acceptance_driver(
        tmp_path, monkeypatch, key, short):
    argvs = _record_runs(monkeypatch)

    def claim(*a, **k):
        raise AssertionError("Pool of Radiance's driver was used")

    monkeypatch.setattr(convertrun.dosbox, "claim", claim)
    save = tmp_path / "SAVGAMA.DAT"
    save.write_bytes(b"")
    played = convertrun.play_dos([save], "A", tmp_path, 2, "D", None, key)
    argv = argvs[0]
    assert pathlib.Path(argv[1]).parts[-3:] == ("tools", "dos", "acceptance.py")
    assert argv[argv.index("--title") + 1] == short
    assert (tmp_path / "acceptance-dos-source" / "SAVGAMA.DAT").is_file()
    assert played["returncode"] == 0


def test_a_dos_title_no_driver_plays_stops_naming_it(tmp_path, monkeypatch):
    argvs = _record_runs(monkeypatch)
    with pytest.raises(SystemExit) as stopped:
        convertrun.play_dos([], "A", tmp_path, 2, "D", None,
                            "pools-of-darkness")
    assert "Pools of Darkness" in str(stopped.value)
    assert argvs == []


# ---------------------------------------------------------------------------
# A walk that never moved the party fails the driver legs
# ---------------------------------------------------------------------------

def _driver_summary(monkeypatch, summary):
    """`subprocess.run` stand-in whose driver exits 0 and leaves `summary`
    as its `summary.json` under the `--out` it was given."""
    import json
    import subprocess

    def run(argv, **kw):
        where = pathlib.Path(argv[argv.index("--out") + 1])
        where.mkdir(parents=True, exist_ok=True)
        (where / "summary.json").write_text(json.dumps(summary))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(convertrun.subprocess, "run", run)


@pytest.mark.parametrize("squares, moved", [(0, False), (2, True)])
def test_a_silver_blades_c64_walk_is_judged_by_the_squares_it_gained(
        tmp_path, monkeypatch, squares, moved):
    _driver_summary(monkeypatch, {"results": [
        {"verb": "walk", "squares_moved": squares}, {"verb": "save"}]})
    monkeypatch.setattr(convertrun, "c64_title",
                        lambda disk: "secret-of-the-silver-blades")
    played = convertrun.play_c64(tmp_path / "W.D64", tmp_path, tmp_path,
                                 "II", True, None)
    assert played["moved"] is moved


@pytest.mark.parametrize("changed, moved", [(False, False), (True, True)])
def test_a_later_dos_walk_is_judged_by_the_saved_place(
        tmp_path, monkeypatch, changed, moved):
    _driver_summary(monkeypatch, {"read": {
        "saved": ["D"], "slots": {"D": {"place_changed": changed}}}})
    save = tmp_path / "SAVGAMA.DAT"
    save.write_bytes(b"")
    played = convertrun.play_dos([save], "A", tmp_path, 2, "D", None,
                                 "secret-of-the-silver-blades")
    assert played["moved"] is moved
