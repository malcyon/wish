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

import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import textwrap
import time

import pytest
import yaml

from automap import gamedisks
from tools.registry import scratch
from tools.suite import datatouch, suiterun

REPO = pathlib.Path(__file__).resolve().parents[2]
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


def _recording(monkeypatch, first_writes=None):
    """Replace `_run` with one that records each pytest call's extra env, and
    every full argument list in `.args`. `first_writes` is called with the first
    pass's extra env, as the recorder would write its log during that pass."""
    calls = _Calls()

    def fake(args, cwd, timeout, extra_env=None):
        if "pytest" in args:
            if first_writes and not calls:
                first_writes(extra_env)
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
    assert set(first) == {datatouch.LOG_ENV}
    assert set(first) & set(_variables().values()) == set()
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
    path = pathlib.Path(next(iter(calls[-1].values())))
    assert not path.is_dir() and not path.exists()
    assert path.parent == tmp_path


def test_the_no_data_pass_runs_only_the_files_that_ask_for_data(tmp_path, monkeypatch):
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    full, narrow = calls.args
    assert "-q" in full
    assert narrow[-1] == "tests/test_reads_disks.py"
    assert "tests/test_plain.py" not in narrow


def _with_the_recorder(worktree):
    (worktree / "tools" / "suite").mkdir()
    (worktree / "tools" / "suite" / "datatouch.py").write_text("")


def _log(worktree, *files):
    directory = worktree.parent / "datatouch"
    directory.mkdir(exist_ok=True)
    (directory / "1.txt").write_text("".join(f"{name}\tstat\n" for name in files))


def test_the_first_pass_loads_the_recorder_and_names_where_it_writes(tmp_path, monkeypatch):
    calls = _recording(monkeypatch)
    worktree = _fake_worktree(tmp_path, registry=True)
    _with_the_recorder(worktree)
    suiterun.run_checks(worktree)
    first = calls.args[0]
    assert first[first.index("-p") + 1] == "tools.suite.datatouch"
    assert calls[0] == {datatouch.LOG_ENV: str(tmp_path / "datatouch")}
    assert "-p" not in calls.args[1]


def test_a_machine_with_no_registry_gets_no_plugin_even_where_the_recorder_exists(
        tmp_path, monkeypatch):
    """The plugin is for the first of two passes; with one pass there is nothing
    to choose files for, and the run gets the empty environment."""
    calls = _recording(monkeypatch)
    worktree = _fake_worktree(tmp_path, registry=False)
    _with_the_recorder(worktree)
    suiterun.run_checks(worktree)
    assert len(calls) == 1
    assert "-p" not in calls.args[0]
    assert datatouch.LOG_ENV not in calls[0]
    assert set(calls[0]) == set(_variables().values())


def test_a_worktree_with_no_recorder_gets_no_plugin_to_load(tmp_path, monkeypatch):
    """A commit older than the recorder has nothing for `-p` to import, and
    pytest stops on a plugin it cannot find."""
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    assert all("-p" not in args for args in calls.args)


def test_the_no_data_pass_runs_exactly_the_files_the_first_pass_recorded(
        tmp_path, monkeypatch, capsys):
    worktree = _fake_worktree(tmp_path, registry=True)
    _with_the_recorder(worktree)
    (worktree / "tests" / "test_gone.py").write_text("def test_x(): pass\n")
    calls = _recording(monkeypatch, lambda env: _log(
        worktree, "tests/test_plain.py", "tests/test_missing.py"))
    green, _, _ = suiterun.run_checks(worktree)
    assert green
    assert calls.args[1][-1:] == ["tests/test_plain.py"]
    assert "tests/test_reads_disks.py" not in calls.args[1]
    out = capsys.readouterr().out
    assert "without data, 1 test files (recorded; the source scan would have chosen 1)" in out


def test_an_empty_log_falls_back_to_the_source_scan(tmp_path, monkeypatch, capsys):
    worktree = _fake_worktree(tmp_path, registry=True)
    _with_the_recorder(worktree)
    calls = _recording(monkeypatch, lambda env: _log(worktree))
    suiterun.run_checks(worktree)
    assert calls.args[1][-1] == "tests/test_reads_disks.py"
    assert "1 test files (source scan; nothing was recorded)" in capsys.readouterr().out


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


def _worktrees(repo):
    return [line for line in _git(repo, "worktree", "list", "--porcelain").splitlines()
            if line.startswith("worktree ")]


def test_a_sigterm_mid_run_removes_the_worktree_and_its_parent(clones, tmp_path, monkeypatch):
    """A `SIGTERM`, as `timeout` sends it, ends `main` through its `finally`: the checkout and the directory holding it go."""
    _, mine = clones
    monkeypatch.setattr(suiterun, "REPO", mine)
    monkeypatch.setattr(suiterun, "RUFF", pathlib.Path(sys.executable))
    monkeypatch.setattr(suiterun, "marker_dir", lambda: tmp_path / "testrun")
    # `tempfile.gettempdir()` caches, so `TMPDIR` set now would not be read.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    seen = {}

    def interrupted(worktree):
        seen["worktree"] = worktree
        assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL
        raise SystemExit(128 + signal.SIGTERM)

    monkeypatch.setattr(suiterun, "run_checks", interrupted)
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as stopped:
        suiterun.main(["HEAD", "--no-rebase"])
    assert stopped.value.code == 128 + signal.SIGTERM
    worktree = seen["worktree"]
    assert worktree.parent.parent == scratch.scratch_dir("suiterun")
    assert not worktree.exists() and not worktree.parent.exists()
    assert len(_worktrees(mine)) == 1
    assert not (tmp_path / "testrun").exists()
    assert signal.getsignal(signal.SIGTERM) is before


def _green_run(mine, tmp_path, monkeypatch, result=(True, "1 passed", "")):
    monkeypatch.setattr(suiterun, "REPO", mine)
    monkeypatch.setattr(suiterun, "RUFF", pathlib.Path(sys.executable))
    monkeypatch.setattr(suiterun, "marker_dir", lambda: tmp_path / "testrun")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(suiterun, "run_checks", lambda worktree: result)
    return suiterun.main(["HEAD", "--no-rebase"])


def test_a_green_run_names_its_marker_for_the_tree_and_not_the_commit(clones, tmp_path, monkeypatch):
    """The push hook looks the tip up by tree, so a name made from the commit would never match."""
    _, mine = clones
    tip = _git(mine, "rev-parse", "HEAD")
    tree = _git(mine, "rev-parse", "HEAD^{tree}")
    assert _green_run(mine, tmp_path, monkeypatch) == 0
    assert [f.name for f in (tmp_path / "testrun").iterdir()] == [f"{tree}.green"]
    assert tip != tree


def test_a_reworded_commit_is_named_for_the_same_marker(clones, tmp_path, monkeypatch):
    _, mine = clones
    before = _git(mine, "rev-parse", "HEAD^{tree}")
    _git(mine, "commit", "-q", "--amend", "-m", "the same files, another sentence")
    assert _git(mine, "rev-parse", "HEAD^{tree}") == before
    assert _green_run(mine, tmp_path, monkeypatch) == 0
    assert [f.name for f in (tmp_path / "testrun").iterdir()] == [f"{before}.green"]


def test_a_rebased_run_is_named_for_the_tree_of_the_rebased_tip(clones, tmp_path, monkeypatch):
    """The marker has to match the tree that gets pushed, which after a rebase is not the tree that was asked for."""
    other, mine = clones
    old = _commit(mine, "mine.txt")
    old_tree = _git(mine, "rev-parse", "HEAD^{tree}")
    _commit(other, "theirs.txt")
    _git(other, "push", "-q", "origin", "main")
    monkeypatch.setattr(suiterun, "REPO", mine)
    monkeypatch.setattr(suiterun, "RUFF", pathlib.Path(sys.executable))
    monkeypatch.setattr(suiterun, "marker_dir", lambda: tmp_path / "testrun")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    tested = {}

    def checked(worktree):
        tested["commit"] = _git(worktree, "rev-parse", "HEAD")
        tested["tree"] = _git(worktree, "rev-parse", "HEAD^{tree}")
        return True, "1 passed", ""

    monkeypatch.setattr(suiterun, "run_checks", checked)
    assert suiterun.main(["HEAD"]) == 0
    assert tested["commit"] != old and tested["tree"] != old_tree
    assert [f.name for f in (tmp_path / "testrun").iterdir()] == [f"{tested['tree']}.green"]


def test_a_red_run_writes_no_marker(clones, tmp_path, monkeypatch):
    _, mine = clones
    assert _green_run(mine, tmp_path, monkeypatch, (False, "1 failed", "FAILED x")) == 1
    assert not (tmp_path / "testrun").exists()


CHILD = textwrap.dedent("""
    import pathlib, sys, time
    from tools.suite import datatouch, suiterun

    suiterun.REPO = pathlib.Path(sys.argv[1])
    suiterun.RUFF = pathlib.Path(sys.executable)
    suiterun.marker_dir = lambda: pathlib.Path(sys.argv[2])
    def waiting(worktree):
        pathlib.Path(sys.argv[3]).write_text("ready")
        time.sleep(120)

    suiterun.run_checks = waiting
    sys.exit(suiterun.main(["HEAD", "--no-rebase"]))
""")


@pytest.mark.skipif(os.name == "nt", reason="SIGTERM is not a signal Windows delivers to a process")
def test_a_real_sigterm_to_the_wrapper_leaves_no_worktree(clones, tmp_path):
    """Send `SIGTERM` to a `main` running in its own process, and read back what is left in the repository and the temp directory."""
    _, mine = clones
    temp = tmp_path / "temp"
    temp.mkdir()
    errors = tmp_path / "child.stderr"
    ready = tmp_path / "ready"
    with errors.open("wb") as fh:
        child = subprocess.Popen(
            [sys.executable, "-c", CHILD, str(mine), str(tmp_path / "testrun"), str(ready)],
            cwd=REPO, stderr=fh,
            env={**os.environ, "TMPDIR": str(temp), "TEMP": str(temp), "TMP": str(temp)})
    try:
        # The child writes `ready` once its checkout is complete, so the signal
        # arrives while the run is checking, not while git is still filling the
        # worktree; the locked case has its own test. A deadline rather than a
        # sleep, because how long a checkout takes on a loaded machine is not
        # something this test should assert.
        deadline = time.time() + 60
        while not ready.exists():
            if child.poll() is not None:
                pytest.fail(f"the wrapper exited {child.returncode} before it "
                            f"was ready:\n{errors.read_text() or '(empty)'}")
            if time.time() > deadline:
                pytest.fail("the wrapper was not ready in 60s")
            time.sleep(0.05)
        child.send_signal(signal.SIGTERM)
        assert child.wait(60) == 128 + signal.SIGTERM, errors.read_text()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    assert len(_worktrees(mine)) == 1
    scratch_root = temp / "wish" / "suiterun"
    assert list(scratch_root.iterdir()) == []


def test_a_worktree_left_locked_by_an_interrupted_checkout_is_still_removed(clones, tmp_path, monkeypatch):
    """`git worktree add` locks a worktree while it fills it, so a run stopped mid-checkout leaves a locked one, which a single `--force` does not remove."""
    _, mine = clones
    monkeypatch.setattr(suiterun, "REPO", mine)
    monkeypatch.setattr(suiterun, "RUFF", pathlib.Path(sys.executable))
    monkeypatch.setattr(suiterun, "marker_dir", lambda: tmp_path / "testrun")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    seen = {}

    def locked(worktree):
        seen["worktree"] = worktree
        _git(mine, "worktree", "lock", str(worktree))
        raise SystemExit(128 + signal.SIGTERM)

    monkeypatch.setattr(suiterun, "run_checks", locked)
    with pytest.raises(SystemExit):
        suiterun.main(["HEAD", "--no-rebase"])
    worktree = seen["worktree"]
    assert not worktree.exists() and not worktree.parent.exists()
    assert len(_worktrees(mine)) == 1


def test_the_sweep_removes_an_abandoned_base_and_leaves_a_live_one(clones, tmp_path, monkeypatch):
    """A killed run leaves a directory git no longer knows; a running one is registered."""
    _, mine = clones
    monkeypatch.setattr(suiterun, "REPO", mine)
    root = tmp_path / "scratch-root"
    live = root / (suiterun._prefix() + "live")
    live.mkdir(parents=True)
    _git(mine, "worktree", "add", "-q", "--detach", str(live / "wt"), "HEAD")
    dead = root / (suiterun._prefix() + "dead")
    (dead / "wt" / "tests").mkdir(parents=True)
    (dead / "wt" / "tests" / "test_x.py").write_text("x\n")
    suiterun._sweep(root)
    assert not dead.exists()
    assert (live / "wt" / "base.txt").is_file()
    assert len(_worktrees(mine)) == 2
    suiterun._sweep(tmp_path / "never-made")


def test_the_sweep_removes_nothing_when_git_cannot_list_the_worktrees(clones, tmp_path, monkeypatch):
    """An empty answer from a failed `git worktree list` would read as "nothing is live"."""
    _, mine = clones
    monkeypatch.setattr(suiterun, "REPO", mine)
    real = suiterun._run

    def failing(args, cwd, timeout, extra_env=None):
        if args[:3] == ["git", "worktree", "list"]:
            return subprocess.CompletedProcess(args, 128, "", "fatal: not a git repository")
        return real(args, cwd, timeout, extra_env)

    monkeypatch.setattr(suiterun, "_run", failing)
    root = tmp_path / "scratch-root"
    base = root / (suiterun._prefix() + "live")
    base.mkdir(parents=True)
    (base / "file").write_text("x\n")
    suiterun._sweep(root)
    assert (base / "file").is_file()


def test_the_sweep_leaves_another_checkouts_base_alone(clones, tmp_path, monkeypatch):
    """Two checkouts share one scratch directory, and only one of them has the base registered."""
    _, mine = clones
    monkeypatch.setattr(suiterun, "REPO", mine)
    root = tmp_path / "scratch-root"
    theirs = root / "run-00000000-abc"
    theirs.mkdir(parents=True)
    (theirs / "file").write_text("x\n")
    assert not theirs.name.startswith(suiterun._prefix())
    suiterun._sweep(root)
    assert (theirs / "file").is_file()


@pytest.mark.skipif(os.name == "nt", reason="creating a symlink needs a privilege on Windows")
def test_the_sweep_does_not_follow_a_symlink_out_of_the_scratch_directory(clones, tmp_path, monkeypatch):
    _, mine = clones
    monkeypatch.setattr(suiterun, "REPO", mine)
    root = tmp_path / "scratch-root"
    root.mkdir()
    target = tmp_path / "somebody-elses-files"
    target.mkdir()
    (target / "file").write_text("x\n")
    (root / (suiterun._prefix() + "link")).symlink_to(target, target_is_directory=True)
    suiterun._sweep(root)
    assert (target / "file").is_file()
