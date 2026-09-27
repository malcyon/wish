"""Checks that `tools/registry/evidence.py` names the run's commit and evidence directory as both acceptance drivers need."""
from __future__ import annotations

import subprocess
import types

import pytest

from tools.registry import evidence, scratch


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path, monkeypatch):
    """No user, system or enclosing-checkout git settings reach the temp repos."""
    empty = tmp_path.parent / f"{tmp_path.name}-gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=repo, check=True, capture_output=True)


def _fake_git(monkeypatch, status, head="0" * 40 + "\n"):
    """Make `evidence` see `status` and `head` as git's output."""
    def run(cmd, **kw):
        out = status if "status" in cmd else head
        return types.SimpleNamespace(returncode=0, stdout=out)
    monkeypatch.setattr(evidence.subprocess, "run", run)


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


def test_a_directory_that_is_not_a_repository_has_an_unknown_sha_and_no_dirty_files(tmp_path):
    assert evidence.git_state(tmp_path) == {"sha": "unknown", "dirty": []}


def test_a_missing_git_binary_raises_file_not_found(repo, monkeypatch):
    def run(*a, **kw):
        raise FileNotFoundError("git")
    monkeypatch.setattr(evidence.subprocess, "run", run)
    with pytest.raises(FileNotFoundError):
        evidence.git_state(repo)


def test_a_merge_conflict_is_listed_once(repo):
    _git(repo, "checkout", "-q", "-b", "other")
    (repo / "a.txt").write_text("other")
    _git(repo, "commit", "-qam", "other")
    _git(repo, "checkout", "-q", "-")
    (repo / "a.txt").write_text("mine")
    _git(repo, "commit", "-qam", "mine")
    merged = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "merge", "other"],
                            cwd=repo, capture_output=True, text=True)
    assert merged.returncode == 1, merged.stdout + merged.stderr
    assert evidence.git_state(repo)["dirty"] == ["a.txt"]


def test_a_non_ascii_path_is_listed_unquoted(repo):
    (repo / "caf\u00e9.txt").write_text("c")
    _git(repo, "add", "-A")
    assert evidence.git_state(repo)["dirty"] == ["caf\u00e9.txt"]


def test_a_path_that_begins_with_a_space_keeps_it(repo):
    (repo / " lead.txt").write_text("c")
    _git(repo, "add", "-A")
    assert evidence.git_state(repo)["dirty"] == [" lead.txt"]


def test_a_copy_is_listed_by_its_new_path_and_its_source_is_skipped(monkeypatch):
    _fake_git(monkeypatch, "C  new.txt\0old.txt\0 M other.txt\0")
    assert evidence.git_state(".")["dirty"] == ["new.txt", "other.txt"]


def test_the_sha_loses_the_newline_git_prints_after_it(monkeypatch):
    _fake_git(monkeypatch, "", head="abc123\n")
    assert evidence.git_state(".")["sha"] == "abc123"


def test_the_evidence_directory_is_issue_then_ten_character_sha_and_run():
    out = evidence.default_out("661", "bless", "0123456789abcdef")
    assert out == scratch.cache_dir("acceptance", "661", "0123456789-bless")
    assert out.parts[-4:] == ("wish", "acceptance", "661", "0123456789-bless")


def test_a_short_sha_is_used_whole():
    assert evidence.default_out("1", "r", "abc").name == "abc-r"


def test_git_output_is_decoded_as_utf_8_with_replacement(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(kw)
        return types.SimpleNamespace(returncode=0, stdout="")
    monkeypatch.setattr(evidence.subprocess, "run", run)
    evidence.git_state(".")
    assert calls
    for kw in calls:
        assert kw["text"] is True
        assert kw["encoding"] == "utf-8"
        assert kw["errors"] == "replace"


def test_a_replacement_character_in_a_path_is_reported_unchanged(monkeypatch):
    _fake_git(monkeypatch, " M caf�.txt\0")
    assert evidence.git_state(".")["dirty"] == ["caf�.txt"]
