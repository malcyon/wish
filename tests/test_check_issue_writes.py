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
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

WINDOWS = os.name == "nt"
HOOK = (pathlib.Path(__file__).resolve().parents[1]
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
    "gh issue edit 470 --add-label AI",
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
    "gh issue reopen 470",
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
]


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


def test_the_refusal_names_the_tool_and_a_runnable_line(capsys, monkeypatch):
    """A refusal nobody can act on is one that gets worked around."""
    assert run("gh issue comment 470 --body-file /tmp/b", monkeypatch) == 2
    err = capsys.readouterr().err
    assert "tools/wishagent.py" in err
    assert "--body-file" in err
    assert "wish-agent[bot]" in err


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
def test_both_harnesses_payload_shapes(tool_input, expected, monkeypatch):
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
    root = pathlib.Path(__file__).resolve().parents[1]

    claude = json.loads((root / ".claude" / "settings.json").read_text())
    commands = [h["command"]
                for group in claude["hooks"].get("PreToolUse", [])
                for h in group["hooks"]]
    assert any("check-issue-writes.py" in c for c in commands)

    codex = json.loads((root / ".codex" / "hooks.json").read_text())
    entries = [h["command"] for h in codex["hooks"].get("PreToolUse", [])]
    assert any("check-issue-writes.py" in c for c in entries)


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
