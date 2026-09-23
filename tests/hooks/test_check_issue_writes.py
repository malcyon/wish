"""`.claude/hooks/check-issue-writes.py` refuses a write that would go out as Donald.

`AGENTS.md` says an agent files and comments with `tools/wishagent.py`, so its
work is authored by `wish-agent[bot]`. **The rule on its own did not hold**: on
2026-09-11, hours after it was written, a subagent finishing a slice of
`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)` posted its findings with
`gh issue comment`. The rule had reached it and it used `gh` anyway, because
that is what every older document shows. This hook is that sentence's
enforcement.

Both halves of the list matter. A hook that refused `gh issue list` or
`gh label` would be switched off inside an hour, and then it would guard
nothing.
"""
import argparse
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

WINDOWS = os.name == "nt"
HOOK = (pathlib.Path(__file__).resolve().parents[2]
        / ".claude" / "hooks" / "check-issue-writes.py")


def _module():
    """Load the hook by path -- a hyphenated filename is not importable."""
    spec = importlib.util.spec_from_file_location("_check_issue_writes", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(command, monkeypatch, tool_name="Bash"):
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": tool_name, "tool_input": {"command": command}})))
    return mod.main()


#: Each has a `tools/wishagent.py` verb, so each refusal has somewhere to go.
REFUSED = [
    "gh issue comment 470 --body-file /tmp/b",
    "gh issue create --title x --body-file /tmp/b",
    "gh issue close 470",
    "gh issue reopen 470",
    "gh issue edit 470 --add-label AI",
    "gh issue edit 470 --title x",
    "gh issue edit 470 --body-file /tmp/b",
    # However the call is reached.
    "cd /tmp && gh issue comment 470 --body-file b",
    "(gh issue comment 470 --body-file b)",
    "bash -c 'gh issue comment 470 --body-file b'",
    "sh -c 'gh issue create --title x --body-file b'",
    "eval 'gh issue comment 470 --body-file b'",
    "/usr/bin/gh issue comment 470 --body-file b",
    "GH_PAGER=cat gh issue comment 470 --body-file b",
    "echo hi | gh issue comment 470 --body-file b",
    # The API route, which says neither "issue" nor "comment".
    "gh api -X POST /repos/malcyon/wish/issues/470/comments -f body=x",
    "gh api --method PATCH /repos/malcyon/wish/issues/470 -f state=closed",
    "gh api -X DELETE /repos/malcyon/wish/issues/470/labels/AI",
]

#: Reads, repository-level commands, and the tool itself. Refusing any of
#: these would make the hook the problem.
ALLOWED = [
    "gh issue list --limit 300 --state open",
    "gh issue view 470 --json number,title",
    "gh api /repos/malcyon/wish/issues/470",
    "gh api --paginate /repos/malcyon/wish/issues",
    "gh label list",
    "gh label create AI --color 5319E7 --description x",
    "gh pr list",
    "gh pr comment 5 --body x",
    "gh run list --limit 5",
    ".venv/bin/python tools/wishagent.py comment 470 --body-file /tmp/b",
    "git commit -m 'stop using gh issue comment'",
    "grep -rn 'gh issue comment' docs/",
]

LOCKING = [
    "gh issue lock 470 --reason resolved",
    "gh issue unlock 470",
]

HEREDOCS = [
    """cat > docs/x.md <<'EOF'
Never run gh issue comment 470 --body-file b
EOF""",
    # A shell reading this body runs it, and nothing in it is banned.
    """sh <<'EOF'
git status
gh issue list --json number
EOF""",
]


def _shell_heredocs(banned):
    """The ways a heredoc reaches a shell, each carrying `banned` in its body."""
    return [
        f"sh <<'EOF'\n{banned}\nEOF",
        f"bash <<EOF\n{banned}\nEOF",
        f"sh 2>&1 <<'EOF'\n{banned}\nEOF",
        f"if true; then sh <<'EOF'\n{banned}\nEOF\nfi",
        f"for i in 1; do sh <<'EOF'\n{banned}\nEOF\ndone",
        f"sh <<'EOF'\n# a note\n{banned}\nEOF",
        f"sh <<'EOF'\n# it's a note\n{banned}\nEOF",
        f"echo \"# h\" > f\nsh <<'EOF'\n{banned}\nEOF",
        f"FOO=1 sh <<'EOF'\n{banned}\nEOF",
        f"bash <<-EOF\n\t{banned}\n\tEOF",
        f"git status && sh <<'EOF'\n{banned}\nEOF",
    ]


#: A body fed to a shell is a script, so what it holds is executed.
SHELL_HEREDOCS = _shell_heredocs("gh issue comment 470 --body-file b")


@pytest.mark.parametrize("command", REFUSED)
def test_a_write_as_donald_is_refused(command, monkeypatch):
    assert run(command, monkeypatch) == 2


@pytest.mark.parametrize("command", ALLOWED)
def test_a_read_or_a_repository_command_is_let_through(command, monkeypatch):
    assert run(command, monkeypatch) == 0


@pytest.mark.parametrize("command", LOCKING)
def test_locking_is_refused_for_its_own_reason(command, monkeypatch, capsys):
    """Locking gets a different message, because it is a different mistake.

    A GitHub App installation is refused a comment on a locked issue whatever
    permissions it holds, measured three ways on 2026-09-11 -- so locking
    silences this project's own bot rather than the public.
    """
    assert run(command, monkeypatch) == 2
    err = capsys.readouterr().err
    assert "locked" in err
    assert "wishagent" not in err       # the write message must not fire here


@pytest.mark.parametrize("command", HEREDOCS)
def test_a_heredoc_that_quotes_the_command_is_let_through(command, monkeypatch):
    """Writing a file that documents the command is not running it.

    `check-issue-reads.py`'s first version refused the edit that wrote its own
    documentation. That lesson is taken here rather than relearnt.
    """
    assert run(command, monkeypatch) == 0


@pytest.mark.parametrize("command", SHELL_HEREDOCS)
def test_a_heredoc_fed_to_a_shell_is_read_as_the_script_it_is(command, monkeypatch):
    """`sh <<'EOF'` executes every line of its body, so a write in it is a real one.

    Stripping the body as data, as `test_a_heredoc_that_quotes_the_command_is_let_through`
    needs for a file being written, let this straight through.
    """
    assert run(command, monkeypatch) == 2


def test_a_banned_command_named_only_in_a_shell_comment_is_let_through(monkeypatch):
    """The shell does not run a comment, so a comment naming the command writes nothing."""
    assert run("git status # gh issue comment 470 --body-file b",
               monkeypatch) == 0


def test_a_shell_fed_on_stdin_by_another_command_is_a_known_limit(monkeypatch):
    """The boundary of the tripwire, recorded so a reader does not mistake it for cover.

    A shell fed through a pipe would need a quoted data argument read as a
    script, which would also refuse `echo 'gh issue comment 470'`, a command
    that is allowed on purpose. `ssh host '...'` names another machine. A
    wrapper in front of the shell (`sudo`, `env`, `nohup`, `exec`, `command`,
    `xargs`) is not looked through, and another interpreter's heredoc body is
    data to this hook whatever it runs.
    """
    banned = "gh issue comment 470 --body-file b"
    for command in [
        f"printf '{banned}\\n' | sh",
        f"ssh host '{banned}'",
        f"sudo sh <<'EOF'\n{banned}\nEOF",
        f"env sh <<'EOF'\n{banned}\nEOF",
        f"sh <<< '{banned}'",
        "python3 <<'PY'\nimport subprocess\n"
        f"subprocess.run('{banned}', shell=True)\nPY",
    ]:
        assert run(command, monkeypatch) == 0, command


def test_a_hash_the_comment_scan_misreads_is_a_known_limit(monkeypatch):
    """The boundary of the comment scan, recorded so a reader does not mistake it for cover.

    Each command below runs a banned write after a `#` that a shell does not
    treat as a comment, and the scan drops the write with it: the `#` sits
    inside backticks, inside a parameter expansion, or after a
    backslash-escaped quote in `$'...'`. All three are allowed today; a fix
    that refuses them should move them to `REFUSED`.
    """
    banned = "gh issue comment 1 --body-file b"
    for command in [
        f"echo `echo #`; {banned}",
        f"echo ${{x:- #foo}}; {banned}",
        f"echo $'\\' #' ; {banned}",
    ]:
        assert run(command, monkeypatch) == 0, command


def test_an_apostrophe_in_a_comment_inside_a_quoted_script_is_a_known_limit(monkeypatch):
    """The boundary of the comment scan, recorded so a reader does not mistake it for cover.

    Comments are dropped from the command line and not from inside a quoted
    `bash -c` script, so the apostrophe in the comment makes `shlex` raise and
    the script is allowed. The same script without the comment line is refused;
    a fix that refuses this one should move it to `REFUSED`.
    """
    banned = "gh issue comment 1 --body-file b"
    assert run(f'bash -c "{banned}"', monkeypatch) == 2
    assert run(f'bash -c "# it\'s a note\n{banned}"', monkeypatch) == 0


def test_an_apostrophe_in_a_shell_comment_does_not_hide_the_script_from_the_scan(monkeypatch):
    """A comment is dropped before the script is tokenised, so its apostrophe cannot break it.

    Left in, the apostrophe makes `shlex` raise and the text fallback finds a
    `gh` with an `issue` and a `comment` in the text, which refuses a script
    that writes nothing.
    """
    command = "sh <<'EOF'\n# it's fine\necho \"gh is right: issue comment\"\nEOF"
    assert run(command, monkeypatch) == 0


def test_the_refusal_names_the_tool_and_a_runnable_line(capsys, monkeypatch):
    """A refusal nobody can act on is one that gets worked around."""
    assert run("gh issue comment 470 --body-file /tmp/b", monkeypatch) == 2
    err = capsys.readouterr().err
    assert "tools/wishagent.py" in err
    assert "--body-file" in err
    assert "wish-agent[bot]" in err


def test_the_refusal_names_the_edit_verb(capsys, monkeypatch):
    """`gh issue edit` is refused, and the message must point somewhere that
    can actually correct a title or a body -- `edit_issue()`'s own verb,
    not one of the other three."""
    assert run("gh issue edit 470 --title x", monkeypatch) == 2
    err = capsys.readouterr().err
    assert "wishagent.py edit" in err


def test_the_refusal_names_the_reopen_verb(capsys, monkeypatch):
    """`gh issue reopen` is refused, and the message must name the verb that
    reopens an issue as the bot."""
    assert run("gh issue reopen 470", monkeypatch) == 2
    err = capsys.readouterr().err
    assert "wishagent.py reopen" in err


def test_a_non_bash_tool_is_ignored(monkeypatch):
    assert run("gh issue comment 470 --body-file b", monkeypatch,
               tool_name="Read") == 0


def test_a_malformed_payload_never_blocks(monkeypatch):
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert mod.main() == 0


@pytest.mark.parametrize("tool_input, expected", [
    ({"command": "gh issue comment 1 --body-file b"}, 2),
    ({"command": ["gh", "issue", "comment", "1", "--body-file", "b"]}, 2),
    ({"command": ["gh", "issue", "list"]}, 0),
    ({"command": 17}, 0),
    ({}, 0),
    (None, 0),
])
def test_both_harnesses_payload_formats(tool_input, expected, monkeypatch):
    """Codex sends the same two fields but may spell Bash's command as argv.

    An unread command makes the hook see nothing and fail open silently, which
    is the worst way for a guard to be wrong.
    """
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": "Bash", "tool_input": tool_input})))
    assert mod.main() == expected


def test_unbalanced_quotes_still_refuse_a_write(monkeypatch):
    """`shlex` cannot parse it, so the safe reading is to refuse.

    A rewrite costs a moment. A comment posted under the wrong identity cannot
    be reauthored.
    """
    assert run('gh issue comment 470 --body-file "unclosed', monkeypatch) == 2


def test_the_hook_is_registered_in_both_harnesses():
    """An unregistered hook guards nothing, and two in this directory are not.

    Claude Code reads `.claude/settings.json`; Codex reads `.codex/hooks.json`.
    One script, two wirings, and the second is the only thing standing between
    a Codex session and the loophole this hook closes.
    """
    root = pathlib.Path(__file__).resolve().parents[2]

    claude = json.loads((root / ".claude" / "settings.json").read_text())
    commands = [h["command"]
                for group in claude["hooks"].get("PreToolUse", [])
                for h in group["hooks"]]
    assert any("check-issue-writes.py" in c for c in commands)

    # Codex's schema nests the same way Claude Code's does: a `matcher`, then
    # an inner `hooks` array. An earlier version of this file used a flat
    # `[{"command": ...}]` taken from a third-party write-up, and Codex showed
    # `PreToolUse  0  0` -- discovered nothing, said nothing.
    codex = json.loads((root / ".codex" / "hooks.json").read_text())
    entries = [h["command"]
               for group in codex["hooks"].get("PreToolUse", [])
               for h in group["hooks"]]
    assert any("check-issue-writes.py" in c for c in entries)
    assert any("check-issue-reads.py" in c for c in entries)


@pytest.mark.skipif(WINDOWS, reason="/usr/bin/python3 does not exist on Windows")
def test_codex_hooks_run_below_the_repository_root(tmp_path):
    """Each configured guard blocks its own bad Bash payload below the root."""
    root = pathlib.Path(__file__).resolve().parents[2]
    codex = json.loads((root / ".codex" / "hooks.json").read_text())
    commands = [h["command"]
                for group in codex["hooks"].get("PreToolUse", [])
                for h in group["hooks"]]
    bad_commands = {
        "check-issue-reads.py": "gh issue view 576 --comments",
        "check-issue-writes.py": "gh issue comment 576 --body nope",
    }
    for command in commands:
        hook = next(name for name in bad_commands if name in command)
        payload = json.dumps({"tool_name": "Bash",
                              "tool_input": {"command": bad_commands[hook]}})
        done = subprocess.run(command, shell=True, cwd=root / "tests" / "hooks",
                              input=payload, capture_output=True, text=True,
                              timeout=30,
                              env=os.environ | {"HOME": str(tmp_path)})
        assert done.returncode == 2, done.stderr
        safe = subprocess.run(
            command, shell=True, cwd=root / "tests" / "hooks",
            input=json.dumps({"tool_name": "Bash",
                              "tool_input": {"command": "git status"}}),
            capture_output=True, text=True, timeout=30,
            env=os.environ | {"HOME": str(tmp_path)})
        assert safe.returncode == 0, safe.stderr


@pytest.mark.skipif(WINDOWS, reason="/usr/bin/python3 does not exist on Windows")
def test_the_hook_runs_under_the_system_interpreter():
    """The harness runs it, not `.venv`, so it must be standard library only."""
    done = subprocess.run(
        ["/usr/bin/python3", str(HOOK)],
        input=json.dumps({"tool_name": "Bash",
                          "tool_input": {"command": "gh issue comment 1 -F b"}}),
        capture_output=True, text=True, timeout=30)
    assert done.returncode == 2
    assert "wishagent.py" in done.stderr


#: Verbs of `tools/wishagent.py` that mint credentials rather than write to an issue.
NOT_ISSUE_WRITES = {"whoami", "token", "push-token", "git-credential"}


def test_the_refusal_names_every_verb_the_tool_has(monkeypatch, capsys):
    """A verb added to the tool is unreachable from the refusal until it is named there."""
    sys.path.insert(0, str(HOOK.parents[2]))
    try:
        import tools.wishagent as wishagent
    finally:
        sys.path.pop(0)
    parser = wishagent.build_parser()
    (subparsers,) = [a for a in parser._actions
                     if isinstance(a, argparse._SubParsersAction)]
    verbs = set(subparsers.choices) - NOT_ISSUE_WRITES
    assert verbs, "the parser lost its subcommands"
    assert run("gh issue comment 470 --body-file /tmp/b", monkeypatch) == 2
    err = capsys.readouterr().err
    missing = sorted(v for v in verbs if f"wishagent.py {v}" not in err)
    assert not missing, f"the refusal does not name {missing}"
