"""`.claude/hooks/check-issue-reads.py` refuses the reads that leak comment text.

The hook is the enforcement half of `tools/issueread.py`: without it the
filtered reader is a convention somebody has to remember, and
`.claude/rules/sessions.md` tells every fresh session to run the unfiltered
form. So what matters is both halves of the list -- that it refuses each form
that would print a comment body, and that it lets through the ordinary reads
this project makes all day. A hook that refused `gh issue list` would be turned
off within the hour, and then it would be guarding nothing.
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
    # `title` and `body` are an issue's own text, just as much as a comment
    # is -- these nine plus the four in
    # test_a_real_call_is_refused_wherever_it_sits_in_the_line got straight
    # through the first version of this hook.
    "gh issue view 510 --json number,title",
    "gh issue list --limit 300 --json number,title",
    "gh issue list --json comments",
    "gh issue view 510 --json title,body",
    "gh search issues --repo malcyon/wish --json title",
    "gh search issues --json body",
    "gh api /repos/malcyon/wish/issues",
    "gh api /repos/malcyon/wish/issues/510",
    "gh api graphql -f query='...'",
    # `gh issue view --web` is refused for a different reason -- see
    # test_web_is_refused_for_the_browser_reason_not_the_trust_one.
    # The exact command `AGENTS.md`'s "Name every issue you cite" and
    # `.claude/rules/issues.md`'s "Citing an issue" both gave before #523 --
    # already caught by the `--json ...,title` check above, kept here as a
    # named regression so a future edit to either cannot silently un-ban it.
    "gh issue view 510 --json number,title -q '\"#\\(.number) (\\(.title))\"'",
]

ALLOWED = [
    "gh issue view 510 --json author,state,labels",
    "gh issue list --limit 300 --state open",
    "gh issue create --title x --body-file /tmp/b",
    "gh issue comment 510 --body-file /tmp/b",
    "gh issue close 510",
    "gh issue edit 510 --add-label bug",
    "gh label list",
    "gh run list",
    "gh pr list",
    ".venv/bin/python tools/issueread.py 510",
    # The one-line citation form #523 gave both rule files, in place of the
    # `--json number,title` command above.
    ".venv/bin/python tools/issueread.py 510 --cite",
    "git log --oneline -3",
    "gh issue list --json number,labels,state",
    # `comments` as a substring of another field must not trip it -- and
    # this no longer carries `title` too, which is banned outright now.
    "gh issue view 510 --json number,state,commentsCount",
    # Talking *about* the command is not running it. The first version of this
    # hook refused the edit that wrote this project's own documentation.
    "grep -rn 'gh issue view --comments' docs/",
    'git commit -m "stop using gh issue view --comments"',
]

#: A heredoc body is data being written to a file, and it is how this project
#: writes every document and every issue body -- so its text quotes commands
#: constantly. These are the forms that were refused in real use.
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
    # Neither the position in the line nor the way `gh` is reached is an
    # anchor any more -- an environment-variable prefix, a word that is not
    # a shell operator, a path to the binary, and a backtick all reach the
    # same `gh issue view --comments`.
    "GH_PAGER=cat gh issue view 510 --comments",
    "then gh issue view 510 --comments",
    "/usr/bin/gh issue view 510 --comments",
    "`gh issue view 510 --comments`",
])
def test_a_real_call_is_refused_wherever_it_sits_in_the_line(command, monkeypatch):
    """Anchoring on command position must not become a way through.

    `shlex` keeps shell punctuation glued to a word, so the subshell form hands
    back `--comments)` -- which the first narrowed version let straight past.
    The first version also anchored on what character came *before* `gh`,
    which is what let the last four of these through.
    """
    assert run(command, monkeypatch=monkeypatch) == 2


@pytest.mark.parametrize("command", [
    "bash -c 'gh issue view 510 --comments'",
    "sh -c \"gh issue view 510 --json comments\"",
    "eval 'gh issue view 510 --comments'",
])
def test_a_call_quoted_as_a_script_for_bash_sh_or_eval_is_refused(command, monkeypatch):
    """`bash -c`, `sh -c` and `eval` all execute their argument as a new
    command line, so a `gh` call quoted inside one is a real invocation --
    unlike the same text quoted for `grep` or `git commit -m`, which never
    runs it. `shlex` folds the whole quoted script into one token, so `gh`
    never appears as a token of its own in the outer command at all; a scan
    that only started at a `gh` token would never reach it.
    """
    assert run(command, monkeypatch=monkeypatch) == 2


def test_web_is_refused_for_the_browser_reason_not_the_trust_one(capsys, monkeypatch):
    """`gh issue view --web` opens a browser on Donald's own screen --
    `AGENTS.md`, "The machine" -- which is a different reason from the trust
    one every other refusal here gives, and reads differently."""
    assert run("gh issue view --web 510", monkeypatch=monkeypatch) == 2
    err = capsys.readouterr().err
    assert "browser" in err
    assert "Donald" in err


def test_the_refusal_names_the_filtered_reader(capsys, monkeypatch):
    """A refusal nobody can act on is a refusal that gets worked around."""
    assert run("gh issue view 510 --comments", monkeypatch=monkeypatch) == 2
    err = capsys.readouterr().err
    assert "tools/issueread.py" in err
    assert "public" in err


def test_the_refusal_names_the_citation_mode(capsys, monkeypatch):
    """#523: the refused command is often the one `AGENTS.md`'s "Name every
    issue you cite" documents, so the refusal must point at the one-line
    replacement rather than only at the whole-issue reader -- a message that
    tells you to print the whole issue when you wanted one line is what gets
    a guard worked around."""
    assert run("gh issue view 510 --json number,title",
               monkeypatch=monkeypatch) == 2
    err = capsys.readouterr().err
    assert "--cite" in err


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


@pytest.mark.skipif(WINDOWS, reason="/usr/bin/python3 does not exist on Windows")
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


@pytest.mark.parametrize("tool_input, expected", [
    ({"command": "gh issue view 510 --comments"}, 2),
    ({"command": ["gh", "issue", "view", "510", "--comments"]}, 2),
    ({"command": ["gh", "issue", "list", "--json", "title"]}, 2),
    ({"command": ["gh", "issue", "list", "--json", "number,state"]}, 0),
    ({"command": 17}, 0),
    ({"command": ["gh", 17]}, 0),
    ({}, 0),
    (None, 0),
    ("not a dict at all", 0),
])
def test_both_harnesses_payload_formats(tool_input, expected, monkeypatch):
    """Codex sends `tool_name`/`tool_input` too, but may spell Bash's command
    as an argv list rather than a string.

    An unread command makes this hook see nothing and fail open **silently**,
    which is the worst way for a guard to be wrong -- so both forms are read,
    and anything unreadable is let through rather than guessed at.
    """
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        json.dumps({"tool_name": "Bash", "tool_input": tool_input})))
    assert mod.main() == expected
