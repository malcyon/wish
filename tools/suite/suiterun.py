#!/usr/bin/env python3
"""Run the whole suite against one commit, in a detached worktree, and record a green run.

    tools/suite/suiterun.py <sha> [--keep]

This is the one run that gates a push (`.claude/rules/commits.md`), made
into a single command so that the green marker is written by the command
that saw the checks pass, and never by an agent concluding that it did.
`.claude/hooks/check-push-tested.py` refuses a `git push` with no marker for
the tip, so `~/.cache/wish/testrun/<sha>.green` is what lets a push through.

What it does, in order, and all of it against the same checkout:

1. `git fetch origin`, then, when `<sha>` is the checked-out branch's tip and
   `origin/main` is not already behind it, `git rebase origin/main`, so the
   marker names the commit that will actually be pushed. A dirty tree, a
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
   every variable `gamedisks.yaml.example` names pointing at one path that
   does not exist. Every `tools/` module is imported in a fresh interpreter,
   then only the test files that ask for game data or decide to skip without it
   are run, so the pass shows nothing depends on data being present without
   repeating the whole suite.
6. `ruff check .` in the worktree.
7. `tools/generate/genui.py --check` in the worktree.
8. If all of it passed, write `~/.cache/wish/testrun/<sha>.green`,
   holding pytest's summary line. On any failure, write nothing.
9. Remove the worktree, whatever happened, unless `--keep`.

Exit status is 0 when the marker was written and 1 otherwise; the decisive
lines of whichever check failed are the last thing printed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tools.registry import scratch  # noqa: E402

PYTHON = REPO / ".venv" / "bin" / "python"


def marker_dir() -> pathlib.Path:
    """Outside the temp directory on purpose: the push hook reads it, and it has
    to survive a reboot. `.claude/hooks/check-push-tested.py` computes the same
    path, and a test fails if the two disagree."""
    return scratch.cache_dir("testrun")


SUMMARY = re.compile(r"^(?:=+ )?(\d+ passed.*?)(?: =+)?$", re.MULTILINE)


def _run(args: list[str], cwd: pathlib.Path, timeout: int,
         extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                               **(extra_env or {})})


def no_data_env(example: pathlib.Path, absent: pathlib.Path) -> dict[str, str]:
    """Every environment variable `example` names, each set to `absent`, a path
    that does not exist.

    A variable that is set is the only place `automap/gamedisks.py`
    looks, so with all of them pointing at nothing no lookup finds any game
    data and every data-backed test skips, as it does on CI. Taking away
    `gamedisks.yaml` alone stopped being enough once `/data/agent-disks`, where
    the example's own paths point, was filled on this machine: with no registry
    the run fell back to the example and found the data anyway.

    The path must not exist rather than merely be empty, because that is what
    CI's own lookups meet (`/data/agent-disks` is not there) and some tests ask
    `.is_dir()` before the registry: `tests/test_cursespellslots.py` skips on
    "no DOS archives" only when the directory is missing, and an empty one made
    it run over the specimen tree alone and fail its measured counts.
    """
    entries = yaml.safe_load(example.read_text(encoding="utf-8")) or {}
    return {row["env"]: str(absent) for row in entries.values()
            if isinstance(row, dict) and row.get("env")}


def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return _run(["git", *args], repo, 300)


def rebase_onto_origin(repo: pathlib.Path, sha: str) -> tuple[str, str]:
    """Fetch origin and rebase the checked-out branch onto `origin/main`.

    Returns the sha to test and a line saying what happened. Only a `sha` that
    is the branch's tip is rebased, because the marker has to name the commit
    that gets pushed. Anything that would leave the tree half-done stops the
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
                    env: dict[str, str]) -> list[str]:
    """One line for each `tools/` module that does not import in a fresh
    interpreter under `env`."""
    def one(module: str) -> str | None:
        done = _run([python, "-c", f"import {module}"], worktree, 180, env)
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


def summary_of(pytest_output: str) -> str:
    found = SUMMARY.findall(pytest_output)
    return found[-1] if found else pytest_output.strip().splitlines()[-1]


def run_checks(worktree: pathlib.Path) -> tuple[bool, str, str]:
    """(all green, pytest summary line, decisive failure output)."""
    python = str(PYTHON)
    no_data = no_data_env(worktree / "gamedisks.yaml.example",
                          worktree.parent / "no-data")
    link = worktree / "gamedisks.yaml"
    # A machine with no registry has nothing to link, so its one run is already
    # the CI-like one and gets the same empty environment.
    pytest = _run([python, "-m", "pytest", "-q"], worktree, 1500,
                  None if link.is_symlink() else no_data)
    print(pytest.stdout[-4000:], end="")
    summary = summary_of(pytest.stdout + pytest.stderr)
    if pytest.returncode != 0:
        failed = [line for line in pytest.stdout.splitlines()
                  if line.startswith(("FAILED", "ERROR"))]
        return False, summary, "\n".join(failed) or pytest.stderr[-2000:]
    if link.is_symlink():
        link.unlink()
        broken = import_failures(worktree, python, no_data)
        print("tool imports without data:",
              f"{len(broken)} failed" if broken else "all import")
        if broken:
            return (False, summary + " (a tool fails to import without data)",
                    "\n".join(broken))
        chosen = data_deciding_tests(worktree / "tests")
        if not chosen:
            return False, summary, "no test file asks for game data: the selection is broken"
        bare = _run([python, "-m", "pytest", "-q", *chosen], worktree, 1500, no_data)
        print(f"without data, {len(chosen)} test files:",
              summary_of(bare.stdout + bare.stderr))
        if bare.returncode != 0:
            failed = [line for line in bare.stdout.splitlines()
                      if line.startswith(("FAILED", "ERROR"))]
            return (False, summary + " (fails without data)",
                    "\n".join(failed) or bare.stderr[-2000:])
    ruff = _run([str(REPO / ".venv" / "bin" / "ruff"), "check", "."], worktree, 300)
    print("ruff:", (ruff.stdout or ruff.stderr).strip().splitlines()[-1])
    if ruff.returncode != 0:
        return False, summary, ruff.stdout[-2000:]
    genui = _run([python, "tools/generate/genui.py", "--check"], worktree, 300)
    print("genui:", (genui.stdout or genui.stderr).strip().splitlines()[-1])
    if genui.returncode != 0:
        return False, summary, (genui.stdout + genui.stderr)[-2000:]
    return True, summary, ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sha", help="the commit to test; resolved with git rev-parse")
    parser.add_argument("--keep", action="store_true",
                        help="leave the worktree behind for a look at a failure")
    parser.add_argument("--no-rebase", action="store_true",
                        help="do not fetch or rebase onto origin/main first")
    args = parser.parse_args(argv)

    sha = resolve(args.sha)
    if not args.no_rebase:
        sha, note = rebase_onto_origin(REPO, sha)
        print(note)
    base = pathlib.Path(tempfile.mkdtemp(prefix="suiterun-"))
    worktree = base / "wt"
    added = _run(["git", "worktree", "add", "-q", "--detach", str(worktree), sha], REPO, 120)
    if added.returncode != 0:
        print(added.stderr.strip())
        return 1
    try:
        if (REPO / "gamedisks.yaml").is_file():
            (worktree / "gamedisks.yaml").symlink_to(REPO / "gamedisks.yaml")
        green, summary, failure = run_checks(worktree)
    finally:
        if not args.keep:
            _run(["git", "worktree", "remove", "--force", str(worktree)], REPO, 120)
            _run(["git", "worktree", "prune"], REPO, 60)
    print(f"target {sha}")
    if not green:
        print("RED, no marker written")
        print(failure)
        return 1
    marker = scratch.ensure(marker_dir()) / f"{sha}.green"
    marker.write_text(summary + "\n")
    print(f"GREEN: {summary}")
    print(f"marker {marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
