"""`.claude/hooks/check-issue-reads.py` refuses the reads that leak comment text.

The hook is the enforcement half of `tools/issueread.py`: without it the
filtered reader is a convention somebody has to remember, and
`.claude/rules/sessions.md` tells every fresh session to run the unfiltered
form. So what matters is both halves of the list -- that it refuses each shape
that would print a comment body, and that it lets through the ordinary reads
this project makes all day. A hook that refused `gh issue list` would be turned
off within the hour, and then it would be guarding nothing.
"""
import importlib.util
import io
import json
import pathlib
import subprocess
import sys

import pytest

HOOK = pathlib.Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "check-issue-reads.py"


def _module():
    """Load the hook by path -- a hyphenated filename is not importable."""
    spec = importlib.util.spec_from_file_location("_check_issue_reads", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(command, tool_name="Bash", monkeypatch=None):
    """Feed the hook a payload the way Claude Code does, and take its exit."""
    mod = _module()
    payload = json.dumps({"tool_name": tool_name,
                          "tool_input": {"command": command}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    return mod.main()


REFUSED = [
    "gh issue view 510 --comments",
    "gh issue view 510 --json number,title,comments",
    "gh issue view 510 --json=comments",
    "gh issue view 510 --json comments,body",
    "gh api /repos/malcyon/wish/issues/510/comments",
    "gh api /repos/malcyon/wish/issues/comments/5628293945",
    "gh api --paginate /repos/malcyon/wish/issues/510/comments",
    # The reason this project reaches for it, straight out of sessions.md.
    "gh issue view 89 --comments | head -50",
]

ALLOWED = [
    "gh issue view 510 --json number,title",
    "gh issue view 510 --json author,state,labels",
    "gh issue list --limit 300 --state open",
    "gh issue create --title x --body-file /tmp/b",
    "gh issue comment 510 --body-file /tmp/b",
    "gh issue close 510",
    "gh label list",
    ".venv/bin/python tools/issueread.py 510",
    "git log --oneline -3",
    # `comments` as a substring of another field must not trip it.
    "gh issue view 510 --json number,title,commentsCount",
    # Talking *about* the command is not running it. The first version of this
    # hook refused the edit that wrote this project's own documentation.
    "grep -rn 'gh issue view --comments' docs/",
    'git commit -m "stop using gh issue view --comments"',
]

#: A heredoc body is data being written to a file, and it is how this project
#: writes every document and every issue body -- so its text quotes commands
#: constantly. These are the shapes that were refused in real use.
HEREDOCS = [
    """cat > docs/x.md <<'EOF'
Read an issue like this:

    gh issue view 510 --comments

That is the command you must not use.
EOF""",
    """python - <<'PY'
sub("Not `gh issue view N\\n--comments`,", "use the reader.")
PY""",
]


@pytest.mark.parametrize("command", REFUSED)
def test_a_read_that_would_print_comment_bodies_is_refused(command, monkeypatch):
    assert run(command, monkeypatch=monkeypatch) == 2


@pytest.mark.parametrize("command", ALLOWED)
def test_an_ordinary_read_is_let_through(command, monkeypatch):
    assert run(command, monkeypatch=monkeypatch) == 0


@pytest.mark.parametrize("command", HEREDOCS)
def test_a_heredoc_that_quotes_the_command_is_let_through(command, monkeypatch):
    """Writing a file that documents the command is not running the command.

    This is a regression test with a date on it: on 2026-09-11 the first
    version of this hook refused the edit that wrote
    `docs/218-the-wish-agent-bot.md`, because the page quotes the command it is
    telling you not to use. A guard that blocks its own documentation is one
    somebody turns off.
    """
    assert run(command, monkeypatch=monkeypatch) == 0


@pytest.mark.parametrize("command", [
    "(gh issue view 510 --comments)",
    "git add -A && gh issue view 510 --comments",
    "echo hi | gh issue view 510 --json comments",
    "cd /tmp; gh issue view 510 --comments",
])
def test_a_real_call_is_refused_wherever_it_sits_in_the_line(command, monkeypatch):
    """Anchoring on command position must not become a way through.

    `shlex` keeps shell punctuation glued to a word, so the subshell form hands
    back `--comments)` -- which the first narrowed version let straight past.
    """
    assert run(command, monkeypatch=monkeypatch) == 2


def test_the_refusal_names_the_filtered_reader(capsys, monkeypatch):
    """A refusal nobody can act on is a refusal that gets worked around."""
    assert run("gh issue view 510 --comments", monkeypatch=monkeypatch) == 2
    err = capsys.readouterr().err
    assert "tools/issueread.py" in err
    assert "public" in err


def test_a_non_bash_tool_is_ignored(monkeypatch):
    """The hook matches Bash; anything else must pass untouched."""
    assert run("gh issue view 510 --comments", tool_name="Read",
               monkeypatch=monkeypatch) == 0


def test_a_malformed_payload_never_blocks(monkeypatch):
    """Blocking on a payload we could not parse would wedge the session."""
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    assert mod.main() == 0


def test_a_non_string_command_never_blocks(monkeypatch):
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        json.dumps({"tool_name": "Bash", "tool_input": {"command": None}})))
    assert mod.main() == 0


def test_unbalanced_quotes_fall_back_to_refusing(monkeypatch):
    """`shlex` cannot parse it, so the safe reading is to refuse.

    A rewrite costs a moment; letting the call through costs the thing the
    hook exists to prevent.
    """
    assert run('gh issue view 510 --comments "unclosed',
               monkeypatch=monkeypatch) == 2


def test_the_hook_is_registered(monkeypatch):
    """An unregistered hook guards nothing, and two here already are not.

    `3ee1a3f "Disable github issue hooks."` took both siblings out of
    `.claude/settings.json`. This one is the enforcement half of a filter, so
    its being registered is part of the behaviour rather than a setting.
    """
    settings = json.loads(
        (pathlib.Path(__file__).resolve().parents[1]
         / ".claude" / "settings.json").read_text())
    commands = [h["command"]
                for group in settings["hooks"].get("PreToolUse", [])
                for h in group["hooks"]]
    assert any("check-issue-reads.py" in c for c in commands)


def test_the_hook_runs_under_the_system_interpreter():
    """It is executed by the harness, not by `.venv`, so it must be stdlib.

    The shebang is `/usr/bin/env python3`; an import this project's virtual
    environment happens to satisfy would fail silently on somebody else's
    machine and take the guard with it.
    """
    done = subprocess.run(
        ["/usr/bin/python3", str(HOOK)],
        input=json.dumps({"tool_name": "Bash",
                          "tool_input": {"command": "gh issue view 1 --comments"}}),
        capture_output=True, text=True, timeout=30)
    assert done.returncode == 2
    assert "issueread.py" in done.stderr
