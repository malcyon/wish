"""The no-registry pass of `tools/suite/suiterun.py` has to find no game data at all.

The pass exists to behave as CI does, and CI has neither a `gamedisks.yaml`
nor any disks. Unlinking the registry was enough until `/data/agent-disks`,
where `gamedisks.yaml.example`'s own paths point, was filled on this machine:
with no registry the loader falls back to the example, found the data there,
and 56 tests that CI skips ran and failed. So the pass sets every variable
the example names to one path that does not exist, which is the only place a
set variable lets the loader look. It must be missing rather than empty:
`tests/test_cursespellslots.py` skips on a missing archives directory and, met
with an empty one, ran over the specimen tree alone and failed its counts.
"""

import pathlib
import subprocess

import pytest
import yaml

from tools.registry import gamedisks
from tools.suite import suiterun

REPO = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "gamedisks.yaml.example"


def _variables():
    entries = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    return {name: row["env"] for name, row in entries.items() if row.get("env")}


def test_every_variable_the_example_names_is_pointed_at_the_one_missing_path(tmp_path):
    missing = tmp_path / "no-data"
    env = suiterun.no_data_env(EXAMPLE, missing)
    assert set(env) == set(_variables().values())
    assert set(env.values()) == {str(missing)}
    assert {"POR_DISKS", "FR_ARCHIVES", "POR_DOS_GAME"} <= set(env)
    assert not missing.exists()


def test_with_those_variables_set_no_entry_resolves_even_where_the_example_points(
        tmp_path, monkeypatch):
    """Both halves of the failure: the variables win over the paths, and a
    missing directory holds nothing for any entry's globs to match."""
    missing = tmp_path / "no-data"
    for var, value in suiterun.no_data_env(EXAMPLE, missing).items():
        monkeypatch.setenv(var, value)
    for name in _variables():
        assert gamedisks.candidates(name) == [missing], name
        assert gamedisks.find(name) is None, name


def _fake_worktree(tmp_path, registry):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "gamedisks.yaml.example").write_bytes(EXAMPLE.read_bytes())
    if registry:
        real = tmp_path / "real.yaml"
        real.write_text("{}\n")
        (worktree / "gamedisks.yaml").symlink_to(real)
    return worktree


def _recording(monkeypatch):
    """Replace `_run` with one that records each pytest call's extra env."""
    calls = []

    def fake(args, cwd, timeout, extra_env=None):
        if "pytest" in args:
            calls.append(extra_env)
        return subprocess.CompletedProcess(args, 0, "1 passed in 0.1s\n", "")

    monkeypatch.setattr(suiterun, "_run", fake)
    return calls


def test_the_pass_without_the_registry_gets_the_empty_environment_and_the_first_does_not(
        tmp_path, monkeypatch):
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    first, bare = calls
    assert first is None
    assert set(bare) == set(_variables().values())
    assert not (tmp_path / "wt" / "gamedisks.yaml").exists()


def test_a_machine_with_no_registry_runs_once_and_with_the_empty_environment(
        tmp_path, monkeypatch):
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=False))
    assert len(calls) == 1
    assert set(calls[0]) == set(_variables().values())


@pytest.mark.parametrize("registry", [True, False])
def test_the_path_is_beside_the_worktree_and_is_not_a_directory(
        tmp_path, monkeypatch, registry):
    """`tests/test_cursespellslots.py` asks `.is_dir()` of the archives and
    skips only when it is false, so an empty directory here is not enough."""
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry))
    path = pathlib.Path(next(v for c in calls if c for v in c.values()))
    assert not path.is_dir() and not path.exists()
    assert path.parent == tmp_path
