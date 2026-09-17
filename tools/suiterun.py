#!/usr/bin/env python3
"""Run the whole suite against one commit, in a detached worktree, and record a green run.

    tools/suiterun.py <sha> [--keep]

This is the one run that gates a push (`.claude/rules/commits.md`), made
into a single command so that the green marker is written by the command
that saw the checks pass, and never by an agent concluding that it did.
`.claude/hooks/check-push-tested.py` refuses a `git push` with no marker for
the tip, so `work/testrun/<sha>.green` is what lets a push through.

What it does, in order, and all of it against the same checkout:

1. `git worktree add --detach` at the resolved sha, so the run tests exactly
   what will land and not whatever other agents have half-edited in the
   main tree.
2. Symlink `work/` into the worktree. It is gitignored, and without it every
   test that reads a specimen from it skips.
3. `pytest -q` in the worktree, with the repository's own virtual
   environment. `-n auto --dist loadgroup` is in `pyproject.toml`.
4. `ruff check .` in the worktree.
5. `tools/genui.py --check` in the worktree.
6. If all three passed, write `work/testrun/<sha>.green` in the main tree,
   holding pytest's summary line. On any failure, write nothing.
7. Remove the worktree, whatever happened, unless `--keep`.

Steps 4 and 5 used to run in the main tree, which meant a marker could say
"green at A" on the strength of a ruff or genui result taken from a dirty
tree that was not A. They run in the worktree now for that reason.

Exit status is 0 when the marker was written and 1 otherwise; the decisive
lines of whichever check failed are the last thing printed.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
PYTHON = REPO / ".venv" / "bin" / "python"
MARKER_DIR = REPO / "work" / "testrun"

SUMMARY = re.compile(r"^(?:=+ )?(\d+ passed.*?)(?: =+)?$", re.MULTILINE)


def _run(args: list[str], cwd: pathlib.Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


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
    pytest = _run([python, "-m", "pytest", "-q"], worktree, 1500)
    print(pytest.stdout[-4000:], end="")
    summary = summary_of(pytest.stdout + pytest.stderr)
    if pytest.returncode != 0:
        failed = [line for line in pytest.stdout.splitlines()
                  if line.startswith(("FAILED", "ERROR"))]
        return False, summary, "\n".join(failed) or pytest.stderr[-2000:]
    ruff = _run([str(REPO / ".venv" / "bin" / "ruff"), "check", "."], worktree, 300)
    print("ruff:", (ruff.stdout or ruff.stderr).strip().splitlines()[-1])
    if ruff.returncode != 0:
        return False, summary, ruff.stdout[-2000:]
    genui = _run([python, "tools/genui.py", "--check"], worktree, 300)
    print("genui:", (genui.stdout or genui.stderr).strip().splitlines()[-1])
    if genui.returncode != 0:
        return False, summary, (genui.stdout + genui.stderr)[-2000:]
    return True, summary, ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sha", help="the commit to test; resolved with git rev-parse")
    parser.add_argument("--keep", action="store_true",
                        help="leave the worktree behind for a look at a failure")
    args = parser.parse_args(argv)

    sha = resolve(args.sha)
    base = pathlib.Path(tempfile.mkdtemp(prefix="suiterun-"))
    worktree = base / "wt"
    added = _run(["git", "worktree", "add", "-q", "--detach", str(worktree), sha], REPO, 120)
    if added.returncode != 0:
        print(added.stderr.strip())
        return 1
    try:
        (worktree / "work").symlink_to(REPO / "work")
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
    MARKER_DIR.mkdir(parents=True, exist_ok=True)
    marker = MARKER_DIR / f"{sha}.green"
    marker.write_text(summary + "\n")
    print(f"GREEN: {summary}")
    print(f"marker {marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
