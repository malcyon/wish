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
# Which DOS game folder `--to dos` writes against (WISH-276)
# ---------------------------------------------------------------------------

POOL = "pool-of-radiance"
SILVER = "secret-of-the-silver-blades"


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """`convertrun.main` with the archives, the source and Save As faked:
    each title's folder is an empty one named for its launcher, and the
    Save As stand-in records the folder it was given and writes nothing."""
    archives = {stem: tmp_path / "archives" / stem
                for stem in ("POOLRAD", "CURSE", "SECRET")}
    for folder in archives.values():
        folder.mkdir(parents=True)
    calls = []

    def find_game(stem="POOLRAD"):
        return archives[stem]

    def save_as(source, to, folder, game, disks, **kwargs):
        calls.append(game)
        return {"written": [], "refused": ["Fake", "nothing written"]}

    title = {}

    class FakeSource:
        @classmethod
        def detect(cls, path, party=None, slot=None):
            return type("Detected", (), {"key": title["key"]})()

    import editor.convert
    monkeypatch.setattr(convertrun.dosbox, "find_game", find_game)
    monkeypatch.setattr(convertrun, "write_via_save_as", save_as)
    monkeypatch.setattr(convertrun, "disks_dir", lambda named=None: tmp_path)
    monkeypatch.setattr(editor.convert, "Source", FakeSource)
    out = tmp_path / "out"

    def run(key, *extra):
        title["key"] = key
        argv = ["--source", str(tmp_path / "SOURCE.D64"), "--to", "dos",
                "--out", str(out), "--no-play", *extra]
        return convertrun.main(argv)

    return run, archives, calls, out


def test_a_silver_blades_source_is_written_against_silver_blades(fake_run):
    """No `--game`: a Silver Blades save is written against the Silver
    Blades folder, not Pool of Radiance's."""
    run, archives, calls, _out = fake_run
    run(SILVER)
    assert calls == [archives["SECRET"]]


@pytest.mark.parametrize("key, stem", [(SILVER, "POOLRAD"),
                                       (POOL, "SECRET")])
def test_a_game_folder_of_another_title_stops_before_writing(
        fake_run, key, stem):
    """A `--game` folder holding another title stops the run with a sentence
    naming both titles, before Save As runs or `--out` is made."""
    run, archives, calls, out = fake_run
    with pytest.raises(SystemExit) as stopped:
        run(key, "--game", str(archives[stem]))
    message = str(stopped.value)
    assert message.startswith("The DOS game folder ")
    assert "but the save is" in message
    assert calls == []
    assert not out.exists()


def test_a_pool_source_is_written_against_pool_as_before(fake_run):
    """A Pool of Radiance save still takes Pool's folder by default, and
    the Pool folder named outright is used as given."""
    run, archives, calls, _out = fake_run
    run(POOL)
    run(POOL, "--game", str(archives["POOLRAD"]))
    assert calls == [archives["POOLRAD"], archives["POOLRAD"]]
