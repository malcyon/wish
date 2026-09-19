"""`tools/registry/scratch.py`: where scratch and the reboot-proof cache live, and that
asking for either creates nothing."""
from __future__ import annotations

import pathlib

import pytest

from tools.registry import scratch


def test_scratch_is_one_directory_per_tool_under_the_temp_directory(
        tmp_path, monkeypatch):
    monkeypatch.setattr(scratch.tempfile, "tempdir", str(tmp_path))
    assert scratch.scratch_dir("dosbox") == tmp_path / "wish" / "dosbox"
    assert scratch.scratch_dir("dosbox", "shots", "1") == (
        tmp_path / "wish" / "dosbox" / "shots" / "1")


def test_asking_for_a_directory_does_not_create_it(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(scratch.pathlib.Path, "home",
                        classmethod(lambda cls: tmp_path / "home"))
    scratch.scratch_dir("instance")
    scratch.cache_dir("testrun")
    assert list(tmp_path.iterdir()) == []


def test_the_cache_is_under_the_home_cache_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch.pathlib.Path, "home",
                        classmethod(lambda cls: tmp_path))
    assert scratch.cache_dir("testrun") == tmp_path / ".cache" / "wish" / "testrun"


def test_ensure_creates_the_directory_and_its_parents(tmp_path):
    made = scratch.ensure(tmp_path / "a" / "b")
    assert made == tmp_path / "a" / "b" and made.is_dir()
    assert scratch.ensure(made) == made


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "../x", "a\\b"])
def test_a_name_that_could_leave_its_own_directory_is_refused(bad):
    with pytest.raises(ValueError):
        scratch.scratch_dir(bad)
    with pytest.raises(ValueError):
        scratch.scratch_dir("ok", bad)
    with pytest.raises(ValueError):
        scratch.cache_dir(bad)


def test_the_scratch_root_is_not_the_checkout():
    repo = pathlib.Path(__file__).resolve().parent.parent
    assert repo not in scratch.scratch_dir("x").parents
