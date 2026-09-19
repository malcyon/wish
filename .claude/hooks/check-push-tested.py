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

So, like `check-orchestrator-edits.py`, this makes the rule mechanical. A
`PreToolUse` hook on Bash: when the command is a `git push`, it looks for a
marker `~/.cache/wish/testrun/<sha>.green`, which `test-runner` writes after
`pytest`, `ruff` and `genui.py --check` all pass at that commit. The push is
allowed when:

  * the tip has a marker; or
  * some ancestor of the tip has a marker and everything between it and the
    tip is prose -- `.md` files outside `.claude/agents/` -- so a README row
    or a document after the run does not need a second run; or
  * everything between the upstream and the tip is prose, which is
    `commits.md`'s own exception, unchanged.

A commit and a push in one call are refused outright: the hook runs before
the call, so it can only vouch for the HEAD it sees, and `git commit && git
push` would push a commit it never checked.

Otherwise it refuses with exit 2, and its stderr, which goes back to the
assistant as the tool's result, says to send the suite to `test-runner`.

**This is a tripwire, not a boundary.** It reads one Bash call as a shell
would tokenise it. A heredoc body is data unless a shell is reading it, in
which case it is a script and is read as one. A comment is dropped by a scan
that respects quoting, so a `#` line inside a shell heredoc hides nothing after
it and a `#` inside ordinary quotes hides nothing. A push through another
interpreter (`python3 <<'EOF'`), a shell fed through a pipe
(`printf 'git push' | sh`), a command line quoted for another machine
(`ssh host 'git push'`), a shell behind a wrapper (`sudo`, `env`, `nohup`,
`exec`, `command`, `xargs`, with or without options) or a push of a branch
other than the checked-out one walks past it. A heredoc nested inside a shell
heredoc is read as part of the script, so its text is judged as commands,
which errs toward refusing. A `#` line inside a quoted `bash -c` or `sh -c`
script hides what follows it, because the outer line's newlines are joined
before the script is read. When git itself cannot answer -- not a repository,
no upstream and no `origin/main` -- it lets the push through rather than
guessing. It exists so the habit of pushing without the run stops working.
"""
import json
import os
import subprocess
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import shellcommands

#: How the message names the marker directory. Not where it is looked for: see
#: `marker_dir`.
MARKER_DIR = "~/.cache/wish/testrun"


def marker_dir() -> str:
    """Where `tools/suite/suiterun.py` writes a green marker: `scratch.cache_dir("testrun")`.

    Computed here rather than imported because the harness runs this hook under
    the system interpreter from whatever directory the command was in, with the
    repository on no path, and a marker directory that lived in the repository
    is what this replaced. `tests/test_check_push_tested.py` fails if the two
    stop agreeing. Looked up at call time so a changed `$HOME` is honoured.
    """
    return os.path.join(os.path.expanduser("~"), ".cache", "wish", "testrun")

#: Where one shell command stops and the next begins. `shlex` with
#: `punctuation_chars` hands these back as their own tokens, so `push;`
#: is two tokens and a quoted script stays one.
BOUNDARY = {"&&", "||", "|", ";", "&", "(", ")", "\n"}

#: `git`'s own options that take a separate argument, so `git -C dir push`
#: is still a push and `git stash push` is not.
GIT_OPTIONS_WITH_ARGUMENT = {"-C", "-c", "--git-dir", "--work-tree",
                             "--namespace", "--exec-path"}

#: Git subcommands that move HEAD, so a push in the same call would push a
#: commit the hook never saw.
MOVES_HEAD = {"commit", "merge", "rebase", "cherry-pick", "reset",
              "checkout", "switch", "pull", "am", "revert"}

#: How many recorded markers `verdict` walks, newest first. Older ones are
#: never the answer, and each costs a `git merge-base`.
MARKERS_CHECKED = 20


def subcommands(command: str, depth: int = 0) -> list[str]:
    """Every git subcommand on the line, in order.

    A plain `git ...` runs one. A shell handed a script (`bash -c '...'`)
    is looked into and reports everything the script runs.
    """
    if depth > 3:
        return []
    # A newline separates commands as `;` does, and `shlex` would fold it.
    script = shellcommands.strip_comments(shellcommands.commands_only(command)).replace("\n", " ; ")
    tokens = shellcommands.tokens(script)
    found = []
    i = 0
    while i < len(tokens):
        token = tokens[i].strip(shellcommands.GLUED)
        base = os.path.basename(token)
        if base == "git":
            j = i + 1
            while j < len(tokens):
                option = tokens[j].strip(shellcommands.GLUED)
                if option in GIT_OPTIONS_WITH_ARGUMENT:
                    j += 2
                elif option.startswith("-"):
                    j += 1
                else:
                    break
            if j < len(tokens) and tokens[j] not in BOUNDARY:
                found.append(tokens[j].strip(shellcommands.GLUED))
            i = j
        elif base in shellcommands.SHELLS or base == "eval":
            j = i + 1
            while j < len(tokens) and tokens[j] not in BOUNDARY:
                if tokens[j] not in ("-c", "-lc", "-ec"):
                    found.extend(subcommands(tokens[j], depth + 1))
                j += 1
            i = j
        else:
            # An environment assignment, a `cd`, or a non-git command: look
            # at the next token rather than the next command, so
            # `GIT_DIR=x git push` is still seen.
            i += 1
    return found


def is_push(command: str) -> bool:
    """Whether any command on the line is a `git push`."""
    return "push" in subcommands(command)


def moves_head_first(command: str) -> bool:
    """Whether a command that moves HEAD runs on the same line as the push.

    The hook runs before the whole call, so it can only vouch for the HEAD it
    sees; `git commit -m x && git push` would push a commit it never checked.
    """
    subs = subcommands(command)
    if "push" not in subs:
        return False
    return any(s in MOVES_HEAD for s in subs[:subs.index("push")])


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
    """A path whose change needs the suite.

    commits.md's exception is for prose: a `.md` that no test reads as data.
    Everything else counts -- `.py`, `.ui`, anything under `tests/`, and
    also `pyproject.toml`, the hook wiring, and the agent TOML files, which
    tests read. `.claude/agents/*.md` is the source the TOML is generated
    from and `tests/test_gencodex.py` checks the two agree, so it counts too.
    """
    if not path.endswith(".md"):
        return True
    return path.startswith(".claude/agents/")


def changed_paths(cwd: str, base: str) -> list[str] | None:
    out = _git(cwd, "diff", "--name-only", f"{base}..HEAD")
    if out is None:
        return None
    return [p for p in out.splitlines() if p.strip()]


def markers() -> list[str]:
    """Recorded green shas, newest first."""
    path = marker_dir()
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
    recorded = markers()
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
        "commit made after the run is fine if it touches only "
        "prose .md files; anything else, including pyproject.toml, an agent "
        "definition or a TOML file, means the run happens again at the new "
        "tip. A push carrying only prose .md changes needs no run.\n")


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
    if moves_head_first(command):
        sys.stderr.write(
            "Refused: this call moves HEAD and pushes in one command, so the "
            "push guard cannot see the commit it would push. Commit in one "
            "call and push in another.\n")
        return 2
    cwd = payload.get("cwd") or os.getcwd()
    refusal = verdict(cwd)
    if refusal is None:
        return 0
    sys.stderr.write(refusal)
    return 2


if __name__ == "__main__":
    sys.exit(main())
