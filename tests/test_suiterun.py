"""`tools/suite/suiterun.py`: the no-data pass finds no game data, and the marker names what gets pushed.

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
import sys

import pytest
import yaml

from automap import gamedisks
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
    (worktree / "tests").mkdir()
    (worktree / "tests" / "test_reads_disks.py").write_text("import gamedisks\n")
    (worktree / "tests" / "test_plain.py").write_text("def test_x(): pass\n")
    (worktree / "tools").mkdir()
    (worktree / "tools" / "__init__.py").write_text("")
    (worktree / "tools" / "one.py").write_text("")
    if registry:
        real = tmp_path / "real.yaml"
        real.write_text("{}\n")
        (worktree / "gamedisks.yaml").symlink_to(real)
    return worktree


class _Calls(list):
    """Each pytest call's extra env, with its whole argument list in `args`."""

    def __init__(self):
        super().__init__()
        self.args = []


def _recording(monkeypatch):
    """Replace `_run` with one that records each pytest call's extra env, and
    every full argument list in `.args`."""
    calls = _Calls()

    def fake(args, cwd, timeout, extra_env=None):
        if "pytest" in args:
            calls.append(extra_env)
            calls.args.append(list(args))
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


def test_the_no_data_pass_runs_only_the_files_that_ask_for_data(tmp_path, monkeypatch):
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    full, narrow = calls.args
    assert full[-1] == "-q"
    assert narrow[-1] == "tests/test_reads_disks.py"
    assert "tests/test_plain.py" not in narrow


def test_the_selection_takes_a_skip_a_needs_marker_or_a_data_lookup(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    for name, body in {
        "test_a.py": "import pytest\npytest.skip('no disks')\n",
        "test_b.py": "from x import needs_dos_saves\n",
        "test_c.py": "from automap import gamedisks\n",
        "test_d.py": "PATH = 'FR_ARCHIVES'\n",
        "test_e.py": "def test_x(): assert 1 + 1 == 2\n",
        "helper.py": "import gamedisks\n",
    }.items():
        (tests / name).write_text(body)
    assert suiterun.data_deciding_tests(tests) == [
        "tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_d.py"]


def test_the_selection_covers_the_files_that_failed_without_data_before():
    """Files that ran and failed once the example's paths held data."""
    chosen = set(suiterun.data_deciding_tests(REPO / "tests"))
    for name in ("test_fleedrive", "test_cursespellslots", "test_doswriter",
                 "test_convert", "test_portraits", "test_amigatodos",
                 "test_dosconvert", "test_dosconversionarea"):
        assert f"tests/{name}.py" in chosen, name


def test_a_tool_that_does_not_import_fails_the_pass(tmp_path):
    worktree = _fake_worktree(tmp_path, registry=True)
    (worktree / "tools" / "broken.py").write_text("import nothing_like_this_exists\n")
    failed = suiterun.import_failures(worktree, sys.executable, {})
    assert len(failed) == 1
    assert any(line.startswith("tools.broken: ") and "nothing_like_this_exists" in line
               for line in failed)
    assert not any(line.startswith("tools.one:") for line in failed)


def test_the_module_list_names_packages_and_modules(tmp_path):
    worktree = _fake_worktree(tmp_path, registry=False)
    (worktree / "tools" / "sub").mkdir()
    (worktree / "tools" / "sub" / "__init__.py").write_text("")
    (worktree / "tools" / "sub" / "two.py").write_text("")
    assert suiterun.tool_modules(worktree) == [
        "tools", "tools.one", "tools.sub", "tools.sub.two"]


def _identity():
    return {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(cwd, *args):
    import os
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **_identity()})
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _commit(repo, name, text="x\n"):
    (repo / name).write_text(text)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def clones(tmp_path, monkeypatch):
    """A bare `origin`, the clone that pushes to it, and the clone under test.

    The identity goes in the environment because `suiterun` runs `git rebase`,
    which makes commits, and CI has no global git identity."""
    for name, value in _identity().items():
        monkeypatch.setenv(name, value)
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    _git(other, "checkout", "-q", "-b", "main")
    _commit(other, "base.txt")
    _git(other, "push", "-q", "origin", "main")
    mine = tmp_path / "mine"
    _git(tmp_path, "clone", "-q", str(origin), str(mine))
    return other, mine


def test_a_branch_already_on_top_of_origin_is_left_alone(clones):
    _, mine = clones
    tip = _commit(mine, "mine.txt")
    assert suiterun.rebase_onto_origin(mine, tip) == (tip, "already on top of origin/main")


def test_a_branch_behind_origin_is_rebased_and_the_new_tip_is_returned(clones):
    other, mine = clones
    old = _commit(mine, "mine.txt")
    _commit(other, "theirs.txt")
    _git(other, "push", "-q", "origin", "main")
    new, note = suiterun.rebase_onto_origin(mine, old)
    assert new != old and new == _git(mine, "rev-parse", "HEAD")
    assert (mine / "theirs.txt").exists() and (mine / "mine.txt").exists()
    assert _git(mine, "merge-base", "--is-ancestor", "origin/main", new) == ""
    assert "rebased onto origin/main" in note and old[:7] in note and new[:7] in note


def test_a_conflict_stops_and_leaves_the_branch_as_it_was(clones):
    other, mine = clones
    old = _commit(mine, "same.txt", "mine\n")
    _commit(other, "same.txt", "theirs\n")
    _git(other, "push", "-q", "origin", "main")
    with pytest.raises(SystemExit) as stopped:
        suiterun.rebase_onto_origin(mine, old)
    assert "rebasing onto origin/main failed" in str(stopped.value)
    assert _git(mine, "rev-parse", "HEAD") == old
    assert not (mine / ".git" / "rebase-merge").exists()
    assert _git(mine, "status", "--porcelain") == ""


def test_a_dirty_tree_stops_the_rebase_before_it_starts(clones):
    other, mine = clones
    old = _commit(mine, "mine.txt")
    _commit(other, "theirs.txt")
    _git(other, "push", "-q", "origin", "main")
    (mine / "mine.txt").write_text("edited\n")
    with pytest.raises(SystemExit) as stopped:
        suiterun.rebase_onto_origin(mine, old)
    assert "uncommitted" in str(stopped.value)
    assert _git(mine, "rev-parse", "HEAD") == old


def test_a_sha_that_is_not_the_tip_is_not_rebased(clones):
    other, mine = clones
    first = _commit(mine, "one.txt")
    _commit(mine, "two.txt")
    _commit(other, "theirs.txt")
    _git(other, "push", "-q", "origin", "main")
    sha, note = suiterun.rebase_onto_origin(mine, first)
    assert sha == first and "not the branch tip" in note


def test_a_failed_fetch_stops_the_run(tmp_path):
    lone = tmp_path / "lone"
    lone.mkdir()
    _git(lone, "init", "-q", "-b", "main")
    tip = _commit(lone, "a.txt")
    with pytest.raises(SystemExit) as stopped:
        suiterun.rebase_onto_origin(lone, tip)
    assert "could not fetch origin" in str(stopped.value)


def test_a_missing_ruff_stops_the_run_before_git_or_pytest_starts(tmp_path, monkeypatch):
    absent = tmp_path / "bin" / "ruff"
    monkeypatch.setattr(suiterun, "RUFF", absent)
    monkeypatch.setattr(suiterun, "marker_dir", lambda: tmp_path / "testrun")

    def forbidden(*args, **kwargs):
        raise AssertionError("something was started with ruff missing")

    monkeypatch.setattr(suiterun, "_run", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(suiterun.tempfile, "mkdtemp", forbidden)
    with pytest.raises(SystemExit) as stopped:
        suiterun.main(["HEAD"])
    message = str(stopped.value)
    assert str(absent) in message and "ruff" in message
    assert "\n" not in message and ".[dev" in message
    assert not (tmp_path / "testrun").exists()
