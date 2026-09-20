"""`tools/suite/suiterun.py`: the no-data pass finds no game data, and the marker names what gets pushed.

The pass exists to behave as CI does, and CI has neither a `gamedisks.yaml`
nor any of the variables `gamedisks.yaml.example` names. So the pass removes
those variables and `WISH_SPECIMENS` from the environment. Setting them to a
path that does not exist would hide the data from the process that runs pytest
but not from a child process: a set variable makes the loader answer before it
reads the registry, so a child that needs the registry would not stop on
`gamedisks.yaml is missing` as it does on CI.

A probe checks that nothing on the machine answers with the variables unset:
not the example's own paths, not the home-folder guesses in `automap.paths`,
not the specimen tree. Where something does, the pass falls back to setting
every variable to one path that does not exist, and says it is not CI's
condition. The one run of a machine with no registry gets the same probe. That
path must be missing rather than empty:
`tests/curse_of_the_azure_bonds/test_cursespellslots.py` skips on a missing
archives directory and, met with an empty one, runs over the specimen tree alone
and fails its counts.
"""

import os
import pathlib
import shutil
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
from tools.suite import suiterun

REPO = pathlib.Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "gamedisks.yaml.example"


def _variables():
    entries = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    return {name: row["env"] for name, row in entries.items() if row.get("env")}


def test_the_fallback_points_every_variable_the_example_names_at_the_one_missing_path(tmp_path):
    """The degraded pass, for a machine where something still answers with the
    variables unset. It is not what CI runs under: a set variable makes a child
    process that needs the registry succeed where CI's stops."""
    missing = tmp_path / "no-data"
    env = suiterun.no_data_env(EXAMPLE, missing)
    assert set(env) == set(_variables().values())
    assert set(env.values()) == {str(missing)}
    assert {"POR_DISKS", "FR_ARCHIVES", "POR_DOS_GAME"} <= set(env)
    assert not missing.exists()


def test_with_the_fallbacks_variables_set_no_entry_resolves_even_where_the_example_points(
        tmp_path, monkeypatch):
    """The degraded pass hides the data from this process: the variables win
    over the paths, and a missing directory holds nothing for any entry's globs
    to match. It does not hide it from a child that needs the registry, which is
    why it is only the fallback."""
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
    (worktree / "tools").mkdir()
    (worktree / "tools" / "__init__.py").write_text("")
    (worktree / "tools" / "one.py").write_text("")
    if registry:
        real = tmp_path / "real.yaml"
        real.write_text("{}\n")
        (worktree / "gamedisks.yaml").symlink_to(real)
    return worktree


@pytest.fixture
def probe_worktree(tmp_path, isolated_example):
    """Real probe modules beside an example whose paths cannot preempt the test's home."""
    worktree = _fake_worktree(tmp_path, registry=False)
    shutil.copyfile(isolated_example, worktree / "gamedisks.yaml.example")
    for package in ("automap", "goldbox"):
        shutil.copytree(REPO / package, worktree / package,
                        ignore=shutil.ignore_patterns("__pycache__"))
    registry = worktree / "tools" / "registry"
    registry.mkdir()
    (registry / "__init__.py").write_text("", encoding="utf-8")
    shutil.copyfile(REPO / "tools" / "registry" / "specimens.py",
                    registry / "specimens.py")
    return worktree


class _Calls(list):
    """Each pytest call's extra env, with its whole argument list in `args`, the
    names it removed from the environment in `without` and each hiding probe
    call in `probes`."""

    def __init__(self):
        super().__init__()
        self.args = []
        self.without = []
        self.probes = []


def _recording(monkeypatch, reachable=(), probe_code=0):
    """Replace `_run` with one that records each pytest call's extra env, the
    names it removes and every full argument list in `.args`. The hiding probe
    answers with a line for each of `reachable` and exits `probe_code`; by
    default nothing is reachable. Each probe call's `cwd`, interpreter and
    removed names are kept in `.probes`."""
    calls = _Calls()

    def fake(args, cwd, timeout, extra_env=None, without=()):
        if args[1:2] == ["-c"] and args[2] == suiterun.PROBE:
            calls.probes.append({"cwd": cwd, "python": args[0],
                                 "without": tuple(without)})
            out = "".join(f"reachable\t{line}\n" for line in reachable)
            return subprocess.CompletedProcess(
                args, probe_code, out + suiterun.PROBE_END + "\n", "")
        if "pytest" in args:
            calls.append(dict(extra_env or {}))
            calls.args.append(list(args))
            calls.without.append(tuple(without))
        return subprocess.CompletedProcess(args, 0, "1 passed in 0.1s\n", "")

    monkeypatch.setattr(suiterun, "_run", fake)
    return calls


def _hidden():
    return set(_variables().values()) | {"WISH_SPECIMENS"}


def test_the_pass_without_the_registry_has_the_variables_unset_and_the_first_does_not(
        tmp_path, monkeypatch):
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    first, bare = calls
    assert first == {}
    assert calls.without[0] == ()
    assert bare == {}
    assert set(calls.without[1]) == _hidden()
    assert not (tmp_path / "wt" / "gamedisks.yaml").exists()


def test_the_probe_runs_in_the_worktree_with_the_venv_python_and_the_hiding_names(
        tmp_path, monkeypatch):
    """The probe asks what the no-data pass will meet, so it runs where that
    pass runs and with the names that pass removes."""
    calls = _recording(monkeypatch)
    worktree = _fake_worktree(tmp_path, registry=True)
    suiterun.run_checks(worktree)
    [probe] = calls.probes
    assert probe["cwd"] == worktree
    assert probe["python"] == str(suiterun.PYTHON)
    assert set(probe["without"]) == _hidden()


def test_a_machine_with_no_registry_runs_once_and_with_the_variables_unset(
        tmp_path, monkeypatch):
    calls = _recording(monkeypatch)
    worktree = _fake_worktree(tmp_path, registry=False)
    suiterun.run_checks(worktree)
    assert len(calls) == 1
    assert calls[0] == {}
    assert set(calls.without[0]) == _hidden()
    [probe] = calls.probes
    assert probe["cwd"] == worktree
    assert set(probe["without"]) == _hidden()


def test_a_machine_with_no_registry_falls_back_and_says_so_where_something_answers(
        tmp_path, monkeypatch, capsys):
    """The one run is the no-data run, so it is held to the same probe: data
    at the example's paths or in a home folder must not pass for CI's condition."""
    calls = _recording(monkeypatch, reachable=["paths\t/home/x/Games/Disks"])
    suiterun.run_checks(_fake_worktree(tmp_path, registry=False))
    assert len(calls) == 1
    assert set(calls[0]) == set(_variables().values())
    assert calls.without[0] == ()
    out = capsys.readouterr().out
    assert "/home/x/Games/Disks" in out and "not the condition CI runs under" in out
    assert "as CI does" not in out


def test_a_machine_with_no_registry_whose_probe_fails_falls_back(
        tmp_path, monkeypatch, capsys):
    calls = _recording(monkeypatch, probe_code=1)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=False))
    assert set(calls[0]) == set(_variables().values())
    assert "the probe failed" in capsys.readouterr().out


def test_the_hidden_variables_are_the_examples_and_the_specimen_tree():
    hidden = suiterun.hidden_variables(EXAMPLE)
    assert set(hidden) == _hidden()
    assert {"POR_DISKS", "FR_ARCHIVES", "POR_DOS_GAME", "WISH_SPECIMENS"} <= set(hidden)


def test_the_variables_the_pass_removes_are_absent_from_its_environment(
        tmp_path, monkeypatch):
    """Every hiding variable is set here first, so an environment that merely
    fails to add one would still contain it."""
    for var in suiterun.hidden_variables(EXAMPLE):
        monkeypatch.setenv(var, str(tmp_path / "somewhere"))
    env = _pass_two_environment(tmp_path, monkeypatch)
    assert not set(suiterun.hidden_variables(EXAMPLE)) & set(env)


def test_the_pass_falls_back_to_the_missing_path_where_something_is_still_reachable(
        tmp_path, monkeypatch, capsys):
    calls = _recording(monkeypatch, reachable=["pool-of-radiance\t/somewhere/disks"])
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    assert set(calls[1]) == set(_variables().values())
    assert calls.without[1] == ()
    out = capsys.readouterr().out
    assert "/somewhere/disks" in out and "not the condition CI runs under" in out


def test_the_pass_falls_back_when_the_probe_itself_fails(tmp_path, monkeypatch, capsys):
    calls = _recording(monkeypatch, probe_code=1)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    assert set(calls[1]) == set(_variables().values())
    assert "the probe failed" in capsys.readouterr().out


def test_the_pass_without_a_fallback_says_it_is_the_condition_ci_runs_under(
        tmp_path, monkeypatch, capsys):
    _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    assert "as CI does" in capsys.readouterr().out


def test_the_probe_names_what_it_finds_and_reads_nothing_from_a_failed_run(
        tmp_path, monkeypatch):
    def answer(stdout, code):
        monkeypatch.setattr(suiterun, "_run", lambda *a, **k: subprocess.CompletedProcess(
            a, code, stdout, ""))
    end = suiterun.PROBE_END + "\n"
    answer("reachable\ta\t/x\nnoise\n" + end, 0)
    assert suiterun.reachable_with_nothing_set(tmp_path, "py", ()) == ["a\t/x"]
    answer(end, 0)
    assert suiterun.reachable_with_nothing_set(tmp_path, "py", ()) == []
    answer("reachable\ta\t/x\n" + end, 1)
    assert suiterun.reachable_with_nothing_set(tmp_path, "py", ()) is None


@pytest.mark.parametrize("stdout", ["", "garbage\n", "reachable\ta\t/x\n",
                                    "probe complete\nreachable\ta\t/x\n"])
def test_a_probe_that_exits_zero_without_its_last_line_is_a_failed_probe(
        tmp_path, monkeypatch, stdout):
    """Empty or garbled output must not read as "nothing is reachable"."""
    monkeypatch.setattr(suiterun, "_run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout, ""))
    assert suiterun.reachable_with_nothing_set(tmp_path, "py", ()) is None


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("py", 120),
                                   FileNotFoundError("py")])
def test_a_probe_that_times_out_or_cannot_start_is_a_failed_probe(
        tmp_path, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(suiterun, "_run", fail)
    assert suiterun.reachable_with_nothing_set(tmp_path, "py", ()) is None


def test_the_probe_finds_disks_in_a_home_folder_guess_with_the_variables_unset(
        tmp_path, monkeypatch, probe_worktree):
    """With `POR_DISKS` unset `automap.paths` falls through to folders under the
    home directory, which the example's paths do not cover."""
    disks = tmp_path / "home" / "Games" / "Pool of Radiance Disks"
    disks.mkdir(parents=True)
    (disks / "POOL1.D64").write_bytes(b"")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    found = suiterun.reachable_with_nothing_set(
        probe_worktree, sys.executable, suiterun.hidden_variables(EXAMPLE))
    assert found is not None
    assert any(line.startswith("automap.paths ") and line.endswith(str(disks))
               for line in found), found


def _home_with(tmp_path, monkeypatch, *folders):
    home = tmp_path / "home"
    for folder in folders:
        (home / folder).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def test_the_probe_finds_the_specimen_tree_with_the_variable_unset(
        tmp_path, monkeypatch, probe_worktree):
    """`WISH_SPECIMENS` is unset, so the tree is `~/wish-specimens`."""
    home = _home_with(tmp_path, monkeypatch, "wish-specimens")
    found = suiterun.reachable_with_nothing_set(
        probe_worktree, sys.executable, suiterun.hidden_variables(EXAMPLE))
    assert found is not None
    assert f"WISH_SPECIMENS\t{home / 'wish-specimens'}" in found, found


#: A file name each title's `disk_glob` matches, for a folder the probe's home
#: guesses would look in.
DISK_FILES = {
    "pool-of-radiance": "POOL1.D64",
    "curse-of-the-azure-bonds": "CURSE1.D64",
    "secret-of-the-silver-blades": "SILVER1.D64",
    "champions-of-krynn": "Champions of Krynn.d64",
    "death-knights-of-krynn": "Death Knights of Krynn.d64",
    "gateway-to-the-savage-frontier": "GATE1.D64",
}


def test_the_probe_finds_every_title_under_its_own_home_folder_guess(
        tmp_path, monkeypatch, probe_worktree):
    """Each title is asked for by itself, so the probe must loop over all of
    them and not only the first few."""
    from goldbox import c64_port
    assert set(DISK_FILES) == {game.key for game in c64_port.GAMES}
    home = _home_with(tmp_path, monkeypatch)
    for game in c64_port.GAMES:
        folder = home / "Games" / game.title
        folder.mkdir(parents=True)
        (folder / DISK_FILES[game.key]).write_bytes(b"")
    found = suiterun.reachable_with_nothing_set(
        probe_worktree, sys.executable, suiterun.hidden_variables(EXAMPLE))
    assert found is not None
    for game in c64_port.GAMES:
        assert f"automap.paths {game.key}\t{home / 'Games' / game.title}" in found, game.key


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX path name can hold a byte that is "
                    "not UTF-8, and a Windows name is UTF-16, so the case cannot arise there")
def test_a_probe_whose_output_is_not_utf8_is_a_failed_probe_with_that_reason(
        tmp_path, monkeypatch, probe_worktree):
    """A home folder whose name ends in a byte that is not UTF-8 puts that byte
    in the probe's output, and decoding it must not crash the run."""
    home = os.fsencode(tmp_path) + b"/h\xff"
    disks = os.path.join(home, b"Games", b"Pool of Radiance Disks")
    os.makedirs(disks)
    open(os.path.join(disks, b"POOL1.D64"), "wb").close()
    monkeypatch.setenv("HOME", os.fsdecode(home))
    monkeypatch.setenv("USERPROFILE", os.fsdecode(home))
    found, reason = suiterun.probe_machine(
        probe_worktree, sys.executable, suiterun.hidden_variables(EXAMPLE))
    assert found is None
    assert "not valid UTF-8" in reason
    assert suiterun.reachable_with_nothing_set(
        probe_worktree, sys.executable, suiterun.hidden_variables(EXAMPLE)) is None


@pytest.mark.parametrize("failure, reason", [
    (subprocess.TimeoutExpired("py", 120), "timed out after 120 s"),
    (FileNotFoundError("no such interpreter"), "could not start: no such interpreter"),
    (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"), "not valid UTF-8"),
    (subprocess.CompletedProcess("py", 3, "", "Traceback\nImportError: boom\n"),
     "exited 3: ImportError: boom"),
    (subprocess.CompletedProcess("py", 0, "reachable\ta\t/x\n", ""),
     "did not print its last line"),
])
def test_the_fallback_line_says_why_the_probe_failed(
        tmp_path, monkeypatch, capsys, failure, reason):
    def fake(*args, **kwargs):
        if isinstance(failure, BaseException):
            raise failure
        return failure

    monkeypatch.setattr(suiterun, "_run", fake)
    extra, without = suiterun.hiding_for_pass_two(
        _fake_worktree(tmp_path, registry=False), "py", ("A",))
    out = capsys.readouterr().out
    assert "the probe failed" in out and reason in out, out
    assert "not the condition CI runs under" in out
    assert without == () and set(extra) == set(_variables().values())


def test_the_fallback_line_names_the_variables_it_sets_and_leaves_the_specimen_tree(
        tmp_path, monkeypatch, capsys):
    _recording(monkeypatch, reachable=["WISH_SPECIMENS\t/home/x/wish-specimens"])
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    out = capsys.readouterr().out
    assert "the example's variables" in out
    assert "specimen tree stays reachable" in out
    assert "every variable" not in out


def test_a_broken_specimen_module_stops_the_probe_and_an_absent_one_does_not(
        tmp_path):
    """A tree without the specimen module has nothing to report; a module
    that fails to import on a current tree is not "no specimens"."""
    def probe_in(tree):
        return subprocess.run([sys.executable, "-c", suiterun.PROBE], cwd=tree,
                              capture_output=True, text=True, timeout=120,
                              env=suiterun._environment(
                                  without=suiterun.hidden_variables(EXAMPLE)))

    def copy(tree, specimens_source):
        shutil.copytree(REPO / "automap", tree / "automap")
        shutil.copytree(REPO / "goldbox", tree / "goldbox")
        shutil.copy(EXAMPLE, tree / "gamedisks.yaml.example")
        registry = tree / "tools" / "registry"
        registry.mkdir(parents=True)
        (tree / "tools" / "__init__.py").write_text("")
        (registry / "__init__.py").write_text("")
        if specimens_source is not None:
            (registry / "specimens.py").write_text(specimens_source)

    old, broken = tmp_path / "old", tmp_path / "broken"
    old.mkdir()
    broken.mkdir()
    copy(old, None)
    copy(broken, "import a_module_that_is_not_installed\n")
    done = probe_in(old)
    assert done.stdout.splitlines()[-1:] == [suiterun.PROBE_END], done.stderr
    done = probe_in(broken)
    assert done.returncode != 0
    assert "a_module_that_is_not_installed" in done.stderr


def test_the_real_probe_runs_and_names_only_paths_that_exist():
    """The probe in a child against this checkout's example. What it finds
    depends on which of the example's paths hold data on the machine, so this
    asserts that it runs and that each line it prints is a path that exists."""
    found = suiterun.reachable_with_nothing_set(
        REPO, sys.executable, suiterun.hidden_variables(EXAMPLE))
    assert found is not None
    for line in found:
        assert pathlib.Path(line.split("\t", 1)[1]).exists()


def test_the_fallback_path_is_beside_the_worktree_and_is_not_a_directory(
        tmp_path, monkeypatch):
    """`tests/curse_of_the_azure_bonds/test_cursespellslots.py` asks `.is_dir()` of the archives and
    skips only when it is false, so an empty directory here is not enough."""
    calls = _recording(monkeypatch, reachable=["pool-of-radiance\t/somewhere"])
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    path = pathlib.Path(next(iter(calls[-1].values())))
    assert not path.is_dir() and not path.exists()
    assert path.parent == tmp_path


def _pass_two_environment(tmp_path, monkeypatch):
    """The environment a child of pass two's pytest starts with, composed the way
    `_run` composes it from what `run_checks` asked for."""
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    return suiterun._environment(calls[-1], calls.without[-1])


LOOKUP = textwrap.dedent("""
    import pathlib, sys
    from automap import gamedisks

    gamedisks.REGISTRY = pathlib.Path(sys.argv[1])
    gamedisks.find("pool-of-radiance")
""")


def test_a_child_that_needs_the_registry_stops_in_the_pass_as_it_does_on_ci(
        tmp_path, monkeypatch):
    """With the variables unset, a child that needs the registry stops on the
    missing one, as it does on CI; a set variable would make `find` answer
    before the registry is read."""
    for var in suiterun.hidden_variables(EXAMPLE):
        monkeypatch.setenv(var, str(tmp_path / "somewhere"))
    env = _pass_two_environment(tmp_path, monkeypatch)
    done = subprocess.run(
        [sys.executable, "-c", LOOKUP, str(tmp_path / "gamedisks.yaml")],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode != 0, done.stdout
    assert "gamedisks.yaml is missing" in done.stderr


def test_the_no_data_pass_runs_the_whole_suite_as_the_first_pass_does(tmp_path, monkeypatch):
    """No file list, so no file that skips without data can be left out and the
    pass is CI's condition by construction."""
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    first, bare = calls.args
    assert bare == [str(suiterun.PYTHON), "-m", "pytest", "-q"]
    assert bare == first


def test_neither_pass_loads_a_plugin_or_names_a_test_file(tmp_path, monkeypatch):
    calls = _recording(monkeypatch)
    suiterun.run_checks(_fake_worktree(tmp_path, registry=True))
    for args in calls.args:
        assert "-p" not in args
        assert not any(arg.startswith("tests") or arg.endswith(".py") for arg in args)


def test_the_import_check_removes_the_names_it_is_given_from_each_childs_environment(
        tmp_path, monkeypatch):
    seen = []

    def fake(args, cwd, timeout, extra_env=None, without=()):
        seen.append((args[2], tuple(without)))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(suiterun, "_run", fake)
    worktree = _fake_worktree(tmp_path, registry=False)
    assert suiterun.import_failures(worktree, "py", ("A", "B")) == []
    assert sorted(code for code, _ in seen) == ["import tools", "import tools.one"]
    assert {without for _, without in seen} == {("A", "B")}


def test_a_tool_that_does_not_import_fails_the_pass(tmp_path):
    worktree = _fake_worktree(tmp_path, registry=True)
    (worktree / "tools" / "broken.py").write_text("import nothing_like_this_exists\n")
    failed = suiterun.import_failures(worktree, sys.executable, ())
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
    from tools.suite import suiterun

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

    def failing(args, cwd, timeout, extra_env=None, without=()):
        if args[:3] == ["git", "worktree", "list"]:
            return subprocess.CompletedProcess(args, 128, "", "fatal: not a git repository")
        return real(args, cwd, timeout, extra_env, without)

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
