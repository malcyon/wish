from __future__ import annotations

"""`tools/gamedisks.py`, the one registry #212 asked for.

Three layers, and the point of the module is their precedence: `$<env>` wins
outright and is taken whole, `gamedisks.local.toml` (gitignored) comes next,
and `gamedisks.toml` (committed) is the search list this project ships. Every
test here points `COMMITTED` and `LOCAL` at files under `tmp_path`, so nothing
depends on the real `gamedisks.toml` except the one test that checks it.
"""


import pathlib

import pytest

from tools import gamedisks


def _write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.write_text(text)
    return path


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """An isolated `gamedisks.toml` with no `gamedisks.local.toml` yet."""
    committed = _write(tmp_path / "committed.toml", """
[a-game]
env = "A_GAME_DISKS"
glob = ["A*.d64"]
paths = ["committed-one", "committed-two"]

[no-default]
env = "NO_DEFAULT_DISKS"
""")
    local = tmp_path / "local.toml"          # not written -- absent on purpose
    monkeypatch.setattr(gamedisks, "COMMITTED", committed)
    monkeypatch.setattr(gamedisks, "LOCAL", local)
    monkeypatch.delenv("A_GAME_DISKS", raising=False)
    monkeypatch.delenv("NO_DEFAULT_DISKS", raising=False)
    # The committed entries above use relative names, the way a real rip's
    # directory name is relative to wherever it was found -- `is_dir()` checks
    # them against the process's own working directory, so tests that create
    # one of those directories need to be standing here when they check it.
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_names_lists_every_committed_entry(registry):
    assert gamedisks.names() == ["a-game", "no-default"]


def test_with_nothing_set_the_committed_paths_are_tried_in_order(registry):
    assert gamedisks.candidates("a-game") == [
        pathlib.Path("committed-one"), pathlib.Path("committed-two")]


def test_an_entry_with_no_paths_has_no_candidates(registry):
    assert gamedisks.candidates("no-default") == []


def test_an_unknown_entry_has_no_candidates(registry):
    assert gamedisks.candidates("nothing-registered-under-this-name") == []


def test_the_environment_variable_wins_outright_and_is_taken_whole(
        registry, monkeypatch):
    monkeypatch.setenv("A_GAME_DISKS", "/wherever/the/player/put/it")
    assert gamedisks.candidates("a-game") == [
        pathlib.Path("/wherever/the/player/put/it")]


def test_the_local_file_is_tried_before_the_committed_one(registry):
    _write(registry / "local.toml", """
[a-game]
paths = ["local-one"]
""")
    assert gamedisks.candidates("a-game") == [
        pathlib.Path("local-one"),
        pathlib.Path("committed-one"), pathlib.Path("committed-two")]


def test_a_path_named_by_both_files_appears_once(registry):
    _write(registry / "local.toml", """
[a-game]
paths = ["committed-one", "local-only"]
""")
    assert gamedisks.candidates("a-game") == [
        pathlib.Path("committed-one"), pathlib.Path("local-only"),
        pathlib.Path("committed-two")]


def test_home_expands_in_every_candidate(registry, monkeypatch):
    _write(registry / "committed.toml", """
[a-game]
env = "A_GAME_DISKS"
paths = ["~/somewhere"]
""")
    monkeypatch.delenv("A_GAME_DISKS", raising=False)
    assert gamedisks.candidates("a-game") == [
        pathlib.Path.home() / "somewhere"]


# -- find(), and both directions it has to prove ------------------------------

def test_find_returns_the_first_candidate_that_actually_matches(registry):
    disks = registry / "committed-two"
    disks.mkdir()
    (disks / "A1.d64").write_bytes(b"")
    assert gamedisks.find("a-game") == pathlib.Path("committed-two")


def test_find_is_none_when_no_candidate_exists(registry):
    assert gamedisks.find("a-game") is None


def test_pointed_at_an_empty_directory_find_is_still_none(registry,
                                                          monkeypatch):
    """The registry's other half of #211's proof: a directory that exists but
    holds nothing does not count as found."""
    empty = registry / "empty"
    empty.mkdir()
    monkeypatch.setenv("A_GAME_DISKS", str(empty))
    assert gamedisks.find("a-game") is None


def test_an_entry_with_no_glob_only_needs_the_directory_to_exist(registry):
    _write(registry / "committed.toml", """
[a-game]
paths = ["a-directory"]
""")
    (registry / "a-directory").mkdir()
    assert gamedisks.find("a-game") == pathlib.Path("a-directory")


# -- report() ------------------------------------------------------------------

def test_report_names_the_environment_variable_as_the_layer(registry,
                                                             monkeypatch):
    (registry / "A1.d64").write_bytes(b"")
    monkeypatch.setenv("A_GAME_DISKS", str(registry))
    rows = {name: row for name, *row in gamedisks.report()}
    assert rows["a-game"][1] == "$A_GAME_DISKS"
    assert rows["a-game"][3] is True


def test_report_says_none_when_nothing_resolves(registry):
    rows = {name: row for name, *row in gamedisks.report()}
    assert rows["no-default"][1] == "none"
    assert rows["no-default"][3] is False


def test_report_names_which_toml_answered(registry):
    disks = registry / "committed-two"
    disks.mkdir()
    (disks / "A1.d64").write_bytes(b"")
    rows = {name: row for name, *row in gamedisks.report()}
    assert rows["a-game"][1] == "gamedisks.toml"
    assert rows["a-game"][3] is True


# -- the file this project actually ships --------------------------------------

def test_every_committed_default_is_found_here_or_marked_unavailable():
    """Every entry in the real `gamedisks.toml` either resolves on this
    machine or carries no default at all, which for `amiga-por-saves` and
    `pod-saves` is `#211 (103 tests skip on the machine that has the game
    files, and the game files are not why)`'s own finding: nobody has
    produced that data on any machine yet.

    Skips as a whole on a machine with none of the game files -- CI, and any
    checkout that is not this one -- because there each entry with a default
    correctly finds nothing, and that is not a regression to report.
    """
    from tests import gamedata
    if gamedata.disk_dir() is None:
        pytest.skip("needs the game disks, to tell 'not on this machine' "
                    "from 'the registry's default is wrong'")
    missing = [name for name in gamedisks.names()
              if gamedisks._committed()[name].get(gamedisks.PATHS)
              and gamedisks.find(name) is None]
    assert missing == []


def test_no_committed_default_points_into_work():
    """`work/` is scratch, gitignored, and has been deleted twice -- a
    default that resolves into it stops resolving the day somebody runs
    `rm -rf work/`, which is what happened to
    `tests/test_silverblades.py`'s old `work/silverblades` entry."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    offenders = [(name, raw)
                for name, row in gamedisks._committed().items()
                for raw in row.get(gamedisks.PATHS, [])
                if (repo / "work") in pathlib.Path(raw).expanduser().parents
                or pathlib.Path(raw).expanduser() == repo / "work"]
    assert offenders == []
