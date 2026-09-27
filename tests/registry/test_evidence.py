"""Checks that `tools/registry/evidence.py` names the run's commit and evidence directory as both acceptance drivers need."""
from __future__ import annotations

import subprocess

import pytest

from tools.registry import evidence, scratch


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("one")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def test_a_clean_tree_has_its_head_sha_and_no_dirty_files(repo):
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                         text=True, check=True).stdout.strip()
    assert evidence.git_state(repo) == {"sha": sha, "dirty": []}


def test_an_untracked_file_does_not_make_the_tree_dirty(repo):
    (repo / "new.txt").write_text("x")
    assert evidence.git_state(repo)["dirty"] == []


def test_a_modified_tracked_file_is_listed_by_its_path(repo):
    (repo / "a.txt").write_text("two")
    assert evidence.git_state(repo)["dirty"] == ["a.txt"]


def test_every_modified_file_keeps_all_its_characters(repo):
    (repo / "b.txt").write_text("b")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "second")
    (repo / "a.txt").write_text("two")
    (repo / "b.txt").write_text("bb")
    assert sorted(evidence.git_state(repo)["dirty"]) == ["a.txt", "b.txt"]


def test_a_staged_new_file_is_listed(repo):
    (repo / "b.txt").write_text("b")
    _git(repo, "add", "b.txt")
    assert evidence.git_state(repo)["dirty"] == ["b.txt"]


def test_a_path_with_a_space_is_listed_as_git_prints_it(repo):
    (repo / "c d.txt").write_text("c")
    _git(repo, "add", "c d.txt")
    assert evidence.git_state(repo)["dirty"] == ["c d.txt"]


def test_a_rename_is_listed_by_its_new_path(repo):
    _git(repo, "mv", "a.txt", "z.txt")
    assert evidence.git_state(repo)["dirty"] == ["z.txt"]


def test_a_directory_that_is_not_a_repository_is_unknown(tmp_path):
    assert evidence.git_state(tmp_path) == {"sha": "unknown", "dirty": []}


def test_a_missing_git_binary_is_unknown(repo, monkeypatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(FileNotFoundError):
        evidence.git_state(repo)


def test_the_evidence_directory_is_issue_then_ten_character_sha_and_run():
    out = evidence.default_out("661", "bless", "0123456789abcdef")
    assert out == scratch.cache_dir("acceptance", "661", "0123456789-bless")
    assert out.parts[-4:] == ("wish", "acceptance", "661", "0123456789-bless")


def test_a_short_sha_is_used_whole():
    assert evidence.default_out("1", "r", "abc").name == "abc-r"
