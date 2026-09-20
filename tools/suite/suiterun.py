#!/usr/bin/env python3
"""Run the whole suite against one commit, in a detached worktree, and record a green run.

    tools/suite/suiterun.py <sha> [--keep]

This is the one run that gates a push (`.claude/rules/commits.md`), made
into a single command so that the green marker is written by the command
that saw the checks pass, and never by an agent concluding that it did.
`.claude/hooks/check-push-tested.py` refuses a `git push` with no marker for
the tip, so `~/.cache/wish/testrun/<tree>.green` is what lets a push through.
`<tree>` is the hash of the tested commit's tree, so a reworded or rebased
commit over the same files still matches and a changed file does not.

What it does, in order, and all of it against the same checkout:

0. Checks that `.venv/bin/ruff` exists, so a missing one stops the run at once
   and not after the whole of pytest.
1. `git fetch origin`, then, when `<sha>` is the checked-out branch's tip and
   `origin/main` is not already behind it, `git rebase origin/main`, so the
   marker is named for the tree that will actually be pushed. A dirty tree, a
   failed fetch or a conflict stops the run with nothing changed; `--no-rebase`
   skips this step.
2. `git worktree add --detach` at the resulting sha, so the run tests exactly
   what will land and not whatever other agents have half-edited in the
   main tree.
3. Symlink `gamedisks.yaml` into the worktree. It is gitignored, and without
   it every test that reads game data skips.
4. `pytest -q` in the worktree, with the repository's own virtual
   environment. `-n auto --dist loadgroup` is in `pyproject.toml`.
5. The no-data pass, which behaves as CI does: `gamedisks.yaml` unlinked and
   every variable `gamedisks.yaml.example` names, and `WISH_SPECIMENS`,
   removed from the environment. Every `tools/` module is imported in a fresh
   interpreter in that environment. A probe then checks that nothing on this
   machine answers for the example's entries once they are gone; if
   something does (the example's paths hold data here), the pass falls back
   to pointing every variable at one path that does not exist, says so, and
   is not the condition CI runs under. Then only the test files the first
   pass saw reach the game data are run (`tools/suite/datatouch.py`, loaded
   into step 4), or, when it recorded nothing, the files whose source asks for
   game data or decides to skip without it, so the pass shows nothing depends
   on data being present without repeating the whole suite.
6. `ruff check .` in the worktree.
7. `tools/generate/genui.py --check` in the worktree.
8. If all of it passed, write `~/.cache/wish/testrun/<tree>.green`,
   holding pytest's summary line. On any failure, write nothing.
9. Remove the worktree and the directory that held it, whatever happened,
   unless `--keep`. A `SIGTERM` is turned into an exit so this still runs, and
   the next run sweeps whatever a `SIGKILL` left under the tool's own scratch
   directory.

Exit status is 0 when the marker was written and 1 otherwise; the decisive
lines of whichever check failed are the last thing printed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tools.registry import scratch  # noqa: E402
from tools.suite import datatouch  # noqa: E402

PYTHON = REPO / ".venv" / "bin" / "python"
RUFF = REPO / ".venv" / "bin" / "ruff"


def marker_dir() -> pathlib.Path:
    """Outside the temp directory on purpose: the push hook reads it, and it has
    to survive a reboot. `.claude/hooks/check-push-tested.py` computes the same
    path, and a test fails if the two disagree."""
    return scratch.cache_dir("testrun")


SUMMARY = re.compile(r"^(?:=+ )?(\d+ passed.*?)(?: =+)?$", re.MULTILINE)


def _environment(extra_env: dict[str, str] | None = None,
                 without: tuple[str, ...] = ()) -> dict[str, str]:
    """This process's environment with `extra_env` added and every name in
    `without` removed, which is the one way to express "not set"."""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", **(extra_env or {})}
    for name in without:
        env.pop(name, None)
    return env


def _run(args: list[str], cwd: pathlib.Path, timeout: int,
         extra_env: dict[str, str] | None = None,
         without: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=_environment(extra_env, without))


def _example_variables(example: pathlib.Path) -> list[str]:
    entries = yaml.safe_load(example.read_text(encoding="utf-8")) or {}
    return [row["env"] for row in entries.values()
            if isinstance(row, dict) and row.get("env")]


def hidden_variables(example: pathlib.Path) -> tuple[str, ...]:
    """Every variable name `example` names, and `WISH_SPECIMENS`: what CI does
    not set, so what the no-data pass removes.

    They are removed rather than pointed at a path that does not exist. A
    variable that is set makes `automap/gamedisks.py` answer before it reads the
    registry, so a child process that needs the registry passed here and stopped
    on `gamedisks.yaml is missing` on CI."""
    return tuple(sorted({*_example_variables(example), "WISH_SPECIMENS"}))


def no_data_env(example: pathlib.Path, absent: pathlib.Path) -> dict[str, str]:
    """Every environment variable `example` names, each set to `absent`, a path
    that does not exist.

    The fallback for a machine where unsetting the variables is not enough:
    the example's own paths hold data there, so with the variables unset and no
    registry the loader finds it anyway. A variable that is set is the only
    place `automap/gamedisks.py` looks, so with all of them pointing at nothing
    no lookup finds any game data and every data-backed test skips. It is not
    the condition CI runs under, because a set variable also stops the loader
    before it reads the registry.

    The path must not exist rather than merely be empty, because that is what
    CI's own lookups meet (`/data/agent-disks` is not there) and some tests ask
    `.is_dir()` before the registry: `tests/curse_of_the_azure_bonds/test_cursespellslots.py` skips on
    "no DOS archives" only when the directory is missing, and an empty one made
    it run over the specimen tree alone and fail its measured counts.
    """
    return {var: str(absent) for var in _example_variables(example)}


#: Run in the worktree with the hiding variables removed and the example in
#: place of the registry, as `tests/conftest.py` does on a machine with none.
#: It prints a line for each entry `gamedisks.find` still answers, and for the
#: specimen tree if it is a directory.
PROBE = """\
from automap import gamedisks
gamedisks.REGISTRY = gamedisks.EXAMPLE
for name in gamedisks.names():
    found = gamedisks.find(name)
    if found is not None:
        print("reachable", name, found, sep="\\t")
try:
    from tools.registry import specimens
except ImportError:
    pass
else:
    if specimens.tree_root().is_dir():
        print("reachable", "WISH_SPECIMENS", specimens.tree_root(), sep="\\t")
"""


def reachable_with_nothing_set(worktree: pathlib.Path, python: str,
                               without: tuple[str, ...]) -> list[str] | None:
    """`name<TAB>path` for each entry that still finds data on this machine when
    the hiding variables are unset and the example stands in for the registry,
    or None when the probe itself failed."""
    done = _run([python, "-c", PROBE], worktree, 120, without=without)
    if done.returncode != 0:
        return None
    return [line.split("\t", 1)[1] for line in done.stdout.splitlines()
            if line.startswith("reachable\t")]


def hiding_for_pass_two(worktree: pathlib.Path, python: str,
                        without: tuple[str, ...]
                        ) -> tuple[dict[str, str], tuple[str, ...]]:
    """`(extra environment, names to remove)` for the no-data pass, and one line
    saying which condition it is.

    Removing the variables is the condition CI runs under. Where the example's
    paths hold data on this machine that hiding leaves the data reachable, so
    the pass falls back to pointing every variable at a path that does not
    exist; a mount namespace that hid the paths themselves is refused on
    machines that forbid unprivileged user namespaces.
    """
    found = reachable_with_nothing_set(worktree, python, without)
    if found == []:
        print("hiding check: nothing answers with the variables unset, so the "
              "no-data pass runs without them, as CI does")
        return {}, without
    why = ("the probe failed" if found is None
           else "still reachable with the variables unset: "
           + "; ".join(line.replace("\t", " at ") for line in found))
    print(f"hiding check: {why}. The no-data pass points every variable at a "
          "path that does not exist instead, which is not the condition CI "
          "runs under")
    return no_data_env(worktree / "gamedisks.yaml.example",
                       worktree.parent / "no-data"), ()


def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return _run(["git", *args], repo, 300)


def rebase_onto_origin(repo: pathlib.Path, sha: str) -> tuple[str, str]:
    """Fetch origin and rebase the checked-out branch onto `origin/main`.

    Returns the sha to test and a line saying what happened. Only a `sha` that
    is the branch's tip is rebased, because the marker is named for the tree of
    the tip that gets pushed. Anything that would leave the tree half-done stops the
    run instead: a failed fetch, a tree with uncommitted changes, or a conflict
    (the rebase is aborted first, so the branch is as it was).
    """
    fetched = _git(repo, "fetch", "-q", "origin")
    if fetched.returncode != 0:
        raise SystemExit("could not fetch origin, nothing was tested:\n"
                         + fetched.stderr.strip())
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if sha != head:
        return sha, f"{sha[:7]} is not the branch tip, so it was not rebased"
    if _git(repo, "merge-base", "--is-ancestor", "origin/main", head).returncode == 0:
        return sha, "already on top of origin/main"
    if _git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise SystemExit("origin/main has moved but the tree has uncommitted "
                         "changes, so it cannot be rebased: commit them or "
                         "set them aside, then run again")
    done = _git(repo, "rebase", "origin/main")
    if done.returncode != 0:
        _git(repo, "rebase", "--abort")
        raise SystemExit("rebasing onto origin/main failed, most likely on a "
                         "conflict; the branch is unchanged. Resolve it, then "
                         "run again:\n"
                         + (done.stdout + done.stderr).strip()[-1500:])
    new = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return new, f"rebased onto origin/main: {head[:7]} -> {new[:7]}"


#: What a test file says when it asks for game data or decides to skip without
#: it: a skip, a `needs_*` marker, or a lookup of disks, archives, specimens or
#: the registry.
DATA_DECIDING = re.compile(
    r"\bskip\w*\(|importorskip|\bneeds_\w+|pytest\.mark\.skip|gamedisks|find_disks"
    r"|specimen|gamedata|automap\.paths|ARCHIVES|_DISKS\b|_SAVES\b|WISH_[A-Z_]+")


def data_deciding_tests(tests: pathlib.Path) -> list[str]:
    """The test files under `tests` that ask for game data or decide to skip
    without it, as paths from the repository root, sorted."""
    return sorted(path.relative_to(tests.parent).as_posix()
                  for path in tests.rglob("test_*.py")
                  if DATA_DECIDING.search(
                      path.read_text(encoding="utf-8", errors="replace")))


def tool_modules(worktree: pathlib.Path) -> list[str]:
    """Every module under `tools/`, as dotted names, packages included."""
    root = worktree / "tools"
    names = []
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(worktree).with_suffix("").parts
        names.append(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return names


def import_failures(worktree: pathlib.Path, python: str,
                    without: tuple[str, ...]) -> list[str]:
    """One line for each `tools/` module that does not import in a fresh
    interpreter with the variables named in `without` unset."""
    def one(module: str) -> str | None:
        done = _run([python, "-c", f"import {module}"], worktree, 180,
                    without=without)
        if done.returncode == 0:
            return None
        tail = (done.stderr.strip().splitlines() or ["no output"])[-1]
        return f"{module}: {tail}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        return [line for line in pool.map(one, tool_modules(worktree)) if line]


def resolve(sha: str) -> str:
    done = _run(["git", "rev-parse", "--verify", f"{sha}^{{commit}}"], REPO, 30)
    if done.returncode != 0:
        raise SystemExit(f"not a commit: {sha}\n{done.stderr.strip()}")
    return done.stdout.strip()


def tree_of(sha: str) -> str:
    """The hash of `sha`'s tree, which is what the marker is named for."""
    done = _run(["git", "rev-parse", "--verify", f"{sha}^{{tree}}"], REPO, 30)
    if done.returncode != 0:
        raise SystemExit(f"no tree for {sha}, nothing was tested:\n{done.stderr.strip()}")
    return done.stdout.strip()


def summary_of(pytest_output: str) -> str:
    found = SUMMARY.findall(pytest_output)
    return found[-1] if found else pytest_output.strip().splitlines()[-1]


def run_checks(worktree: pathlib.Path) -> tuple[bool, str, str]:
    """(all green, pytest summary line, decisive failure output)."""
    python = str(PYTHON)
    hidden = hidden_variables(worktree / "gamedisks.yaml.example")
    link = worktree / "gamedisks.yaml"
    log_dir = worktree.parent / "datatouch"
    # The first pass records which test files reach the game data, when this
    # commit has the recorder to load: a commit older than it has no plugin for
    # `-p` to import, and pytest would stop on the missing name. A machine with
    # no registry has one run and no second pass to choose files for.
    first_args = [python, "-m", "pytest", "-q"]
    if link.is_symlink() and (worktree / "tools" / "suite" / "datatouch.py").is_file():
        first_args += ["-p", "tools.suite.datatouch"]
    # A machine with no registry has nothing to link, so its one run is already
    # the CI-like one and has the same variables unset.
    if link.is_symlink():
        pytest = _run(first_args, worktree, 1500, {datatouch.LOG_ENV: str(log_dir)})
    else:
        pytest = _run(first_args, worktree, 1500, without=hidden)
    print(pytest.stdout[-4000:], end="")
    summary = summary_of(pytest.stdout + pytest.stderr)
    if pytest.returncode != 0:
        failed = [line for line in pytest.stdout.splitlines()
                  if line.startswith(("FAILED", "ERROR"))]
        return False, summary, "\n".join(failed) or pytest.stderr[-2000:]
    if link.is_symlink():
        link.unlink()
        broken = import_failures(worktree, python, hidden)
        print("tool imports without data:",
              f"{len(broken)} failed" if broken else "all import")
        if broken:
            return (False, summary + " (a tool fails to import without data)",
                    "\n".join(broken))
        scanned = data_deciding_tests(worktree / "tests")
        touched = datatouch.recorded(log_dir, worktree)
        chosen = touched or scanned
        if not chosen:
            return False, summary, "no test file asks for game data: the selection is broken"
        how = (f"recorded; the source scan would have chosen {len(scanned)}"
               if touched else "source scan; nothing was recorded")
        extra, without = hiding_for_pass_two(worktree, python, hidden)
        bare = _run([python, "-m", "pytest", "-q", *chosen], worktree, 1500,
                    extra, without)
        print(f"without data, {len(chosen)} test files ({how}):",
              summary_of(bare.stdout + bare.stderr))
        if bare.returncode != 0:
            failed = [line for line in bare.stdout.splitlines()
                      if line.startswith(("FAILED", "ERROR"))]
            return (False, summary + " (fails without data)",
                    "\n".join(failed) or bare.stderr[-2000:])
    ruff = _run([str(RUFF), "check", "."], worktree, 300)
    print("ruff:", (ruff.stdout or ruff.stderr).strip().splitlines()[-1])
    if ruff.returncode != 0:
        return False, summary, ruff.stdout[-2000:]
    genui = _run([python, "tools/generate/genui.py", "--check"], worktree, 300)
    print("genui:", (genui.stdout or genui.stderr).strip().splitlines()[-1])
    if genui.returncode != 0:
        return False, summary, (genui.stdout + genui.stderr)[-2000:]
    return True, summary, ""


def _prefix() -> str:
    """What names this checkout's bases under the shared scratch directory, so a run in another checkout leaves them alone."""
    return f"run-{hashlib.sha1(str(REPO).encode()).hexdigest()[:8]}-"


def _sweep(root: pathlib.Path) -> None:
    """Remove this checkout's bases under `root` that no registered worktree lives in.

    What an earlier run that was killed outright left behind. A suite running
    now has its worktree registered, so it is left alone; this assumes one
    run at a time per checkout, which is the rule. Nothing is removed when git
    cannot list the worktrees, since an empty list would read as "none is
    live", and a symlink is skipped rather than followed out of `root`.
    """
    _run(["git", "worktree", "prune"], REPO, 60)
    if not root.is_dir():
        return
    listed = _run(["git", "worktree", "list", "--porcelain"], REPO, 60)
    if listed.returncode != 0:
        return
    live = [pathlib.Path(line[len("worktree "):]).resolve()
            for line in listed.stdout.splitlines() if line.startswith("worktree ")]
    for child in root.iterdir():
        if child.is_symlink() or not child.name.startswith(_prefix()):
            continue
        held = child.resolve()
        if not any(path == held or held in path.parents for path in live):
            shutil.rmtree(child, ignore_errors=True)


def _terminate(signum: int, frame: object) -> None:
    """Turn `SIGTERM` into an exit, so a `timeout` that sends it still runs the `finally` in `main`."""
    raise SystemExit(128 + signum)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sha", help="the commit to test; resolved with git rev-parse")
    parser.add_argument("--keep", action="store_true",
                        help="leave the worktree behind for a look at a failure")
    parser.add_argument("--no-rebase", action="store_true",
                        help="do not fetch or rebase onto origin/main first")
    args = parser.parse_args(argv)

    if not RUFF.is_file():
        raise SystemExit(f"{RUFF} is missing, so nothing was tested: "
                         'run pip install -e ".[dev,gui]" in the virtual environment')
    sha = resolve(args.sha)
    if not args.no_rebase:
        sha, note = rebase_onto_origin(REPO, sha)
        print(note)
    tree = tree_of(sha)
    root = scratch.scratch_dir("suiterun")
    _sweep(root)
    base = pathlib.Path(tempfile.mkdtemp(prefix=_prefix(), dir=scratch.ensure(root)))
    worktree = base / "wt"
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        added = _run(["git", "worktree", "add", "-q", "--detach", str(worktree), sha], REPO, 120)
        if added.returncode != 0:
            print(added.stderr.strip())
            return 1
        if (REPO / "gamedisks.yaml").is_file():
            (worktree / "gamedisks.yaml").symlink_to(REPO / "gamedisks.yaml")
        green, summary, failure = run_checks(worktree)
    finally:
        signal.signal(signal.SIGTERM, previous)
        if not args.keep:
            # Twice, because git locks a worktree while it fills it and a run
            # stopped mid-checkout leaves a locked one, which one `--force`
            # does not remove.
            _run(["git", "worktree", "remove", "--force", "--force", str(worktree)], REPO, 120)
            _run(["git", "worktree", "prune"], REPO, 60)
            shutil.rmtree(base, ignore_errors=True)
    print(f"target {sha} tree {tree}")
    if not green:
        print("RED, no marker written")
        print(failure)
        return 1
    marker = scratch.ensure(marker_dir()) / f"{tree}.green"
    marker.write_text(summary + "\n")
    print(f"GREEN: {summary}")
    print(f"marker {marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
