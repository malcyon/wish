"""`tools/convert/convertrun.py` and `tools/convert/saveasdrive.py` publish through
Save As, so what the emulator boots is what the editor's Save As writes.

Both tests need a DOS save and the player's own C64 disks and skip cleanly
without either.
"""

from __future__ import annotations

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

    assert "refused" not in report
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

    assert "refused" not in report
    (written,) = [p for p in report["written"] if p.endswith(".D64")]
    landed = [m.name for m in
              Party(Source.detect(pathlib.Path(written))).members]
    assert landed == b_names


@needs_dos_saves
@needs_disks
def test_a_refused_save_as_writes_nothing_and_says_why(tmp_path, monkeypatch):
    """A conversion Save As refuses is reported under `refused`, and nothing
    lands under the output folder."""
    def refuse(*args, **kwargs):
        raise saveplan.DroppedFields(["a field the writer cannot hold"])

    monkeypatch.setattr(saveplan, "prepare_save_as", refuse)
    out = tmp_path / "out"
    out.mkdir()

    report = convertrun.write_via_save_as(_save_dir() / "SAVGAMA.DAT", "c64",
                                          out, None, disk_dir())

    assert report["refused"][0] == "DroppedFields"
    assert "written" not in report
    assert list(out.glob("wish-*")) == []


def test_leave_chooses_the_item_an_over_limit_pack_leaves_behind(
        tmp_path, monkeypatch):
    """A pack needing 17 C64 slots is refused without `leave` and converts
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

    refused = convertrun.write_via_save_as(folder, "c64", out, None, disks,
                                           source_slot="A")
    assert refused["refused"][0] == "JoinedScrollsDoNotFit", refused
    assert NO_LEAVE_MESSAGE in refused["refused"][1]
    assert "written" not in refused

    report = convertrun.write_via_save_as(folder, "c64", out, None, disks,
                                          source_slot="A", leave={0: {3}})
    assert "refused" not in report, report
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
        return {"written": [], "refused": ["Fake", "nothing written"]}

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


def test_no_encounters_is_refused_for_a_dos_destination(tmp_path):
    with pytest.raises(SystemExit):
        convertrun.main(["--source", str(tmp_path / "S.D64"), "--to", "dos",
                         "--out", str(tmp_path / "out"), "--no-encounters"])
    assert not (tmp_path / "out").exists()
