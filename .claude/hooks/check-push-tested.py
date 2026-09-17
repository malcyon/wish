#!/usr/bin/env python3
"""Refuse a `git push` until test-runner has recorded a green suite for what is being pushed.

`.claude/rules/commits.md` says the whole suite runs once, in a detached
worktree, before every push that carries code. **The rule did not hold**: on
2026-09-16 the orchestrator pushed eighteen times and launched `test-runner`
once, and the batch that closed `#89` turned `main` red on a test in
`tests/test_debugmode.py` that neither the builder nor the reviewer had run,
because both were scoped to the builder's files by design. Only the full
suite covers a test elsewhere in the tree that asserts the old behaviour,
and the full suite was the step that was skipped.

So, like `check-context-handoff.py`, this makes the rule mechanical. A
`PreToolUse` hook on Bash: when the command is a `git push`, it looks for a
marker `work/testrun/<sha>.green`, which `test-runner` writes after
`pytest`, `ruff` and `genui.py --check` all pass at that commit. The push is
allowed when:

  * the tip has a marker; or
  * some ancestor of the tip has a marker and everything between it and the
    tip is documentation -- no `.py`, no `.ui`, nothing under `tests/` -- so
    the orchestrator's queue-file commit after the run does not need a
    second run; or
  * everything between the upstream and the tip is documentation, which is
    `commits.md`'s own exception, unchanged.

Otherwise it refuses with exit 2, and its stderr, which goes back to the
assistant as the tool's result, says to send the suite to `test-runner`.

**This is a tripwire, not a boundary.** It reads one Bash call as a shell
would tokenise it; a push through another interpreter, or a push of a branch
other than the checked-out one, walks past it. When git itself cannot answer
-- not a repository, no upstream and no `origin/main` -- it lets the push
through rather than guessing. It exists so the habit of pushing without the
run stops working.
"""
import json
import os
import re
import shlex
import subprocess
import sys

MARKER_DIR = os.path.join("work", "testrun")

#: Heredoc bodies are data being written to a file, not commands being run,
#: and this project's documents quote `git push` constantly.
HEREDOC = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1.*?^\s*\2\s*$",
    re.DOTALL | re.MULTILINE)

#: Where one shell command stops and the next begins. Split on these before
#: tokenising, because `shlex` treats `push;` as one word.
SEPARATORS = re.compile(r"\|\||&&|[;&|\n]")

#: Shell punctuation glued to a token with no space.
GLUED = "`(){}[]<>$"

#: Interpreters whose argument is a new command line.
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}

#: `git`'s own options that take a separate argument, so `git -C dir push`
#: is still a push and `git stash push` is not.
GIT_OPTIONS_WITH_ARGUMENT = {"-C", "-c", "--git-dir", "--work-tree",
                             "--namespace", "--exec-path"}

#: How many recorded markers `verdict` walks, newest first. Older ones are
#: never the answer, and each costs a `git merge-base`.
MARKERS_CHECKED = 20


def commands_only(command: str) -> str:
    """What the shell would execute, with heredoc bodies removed."""
    return HEREDOC.sub("\n", command)


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _is_push_command(tokens: list[str], depth: int) -> bool:
    """Whether one shell command, already split off, is `git push`."""
    for i, raw in enumerate(tokens):
        token = raw.strip(GLUED)
        base = os.path.basename(token)
        if base == "git":
            j = i + 1
            while j < len(tokens):
                option = tokens[j].strip(GLUED)
                if option in GIT_OPTIONS_WITH_ARGUMENT:
                    j += 2
                elif option.startswith("-"):
                    j += 1
                else:
                    break
            return j < len(tokens) and tokens[j].strip(GLUED) == "push"
        if base in SHELLS or base == "eval":
            return any(is_push(arg, depth + 1) for arg in tokens[i + 1:]
                       if arg not in ("-c", "-lc", "-ec"))
    return False


def is_push(command: str, depth: int = 0) -> bool:
    """Whether any command on the line is a `git push`."""
    if depth > 3:
        return False
    for piece in SEPARATORS.split(commands_only(command)):
        if piece.strip() and _is_push_command(_tokens(piece), depth):
            return True
    return False


def _git(cwd: str, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def is_code(path: str) -> bool:
    """A path whose change needs the suite, per commits.md's exception."""
    return (path.endswith(".py") or path.endswith(".ui")
            or path.startswith("tests/"))


def changed_paths(cwd: str, base: str) -> list[str] | None:
    out = _git(cwd, "diff", "--name-only", f"{base}..HEAD")
    if out is None:
        return None
    return [p for p in out.splitlines() if p.strip()]


def markers(root: str) -> list[str]:
    """Recorded green shas, newest first."""
    path = os.path.join(root, MARKER_DIR)
    try:
        names = [n for n in os.listdir(path) if n.endswith(".green")]
    except OSError:
        return []
    names.sort(key=lambda n: os.path.getmtime(os.path.join(path, n)),
               reverse=True)
    return [n[:-len(".green")] for n in names]


def verdict(cwd: str) -> str | None:
    """None to allow the push, or the refusal to print."""
    root = _git(cwd, "rev-parse", "--show-toplevel")
    head = _git(cwd, "rev-parse", "HEAD")
    if not root or not head:
        return None
    recorded = markers(root)
    if head in recorded:
        return None
    for sha in recorded[:MARKERS_CHECKED]:
        if _git(cwd, "merge-base", "--is-ancestor", sha, "HEAD") is None:
            continue
        between = changed_paths(cwd, sha)
        if between is not None and not any(is_code(p) for p in between):
            return None
    carried = changed_paths(cwd, "@{upstream}")
    if carried is None:
        carried = changed_paths(cwd, "origin/main")
    if carried is None:
        return None
    if not any(is_code(p) for p in carried):
        return None
    return (
        f"Refused: no green suite is recorded for {head}. Send the whole "
        "suite to test-runner at this commit; on a green run it writes "
        f"{MARKER_DIR}/{head}.green, and then the push goes through. A "
        "commit made after the run is fine if it touches no .py, .ui or "
        "tests/ file; otherwise the run happens again at the new tip. A "
        "push carrying no .py, .ui or tests/ change needs no run.\n")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not is_push(command):
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    refusal = verdict(cwd)
    if refusal is None:
        return 0
    sys.stderr.write(refusal)
    return 2


if __name__ == "__main__":
    sys.exit(main())
