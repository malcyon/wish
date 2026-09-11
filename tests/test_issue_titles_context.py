"""Tests for `.claude/hooks/issue-titles-context.py`.

Loaded by path because the filename is hyphenated -- the same idiom
`.claude/hooks/check-gh-issue-titles.py` uses for its own sibling.

The repository is public with issues enabled, so an issue's author is
attacker-controlled: anyone can open one. The two regression tests that
matter most are the first two below -- the hook exists to stop a rule that
kept getting broken, and a change that quietly withheld the project's own
titles would reintroduce that problem.
"""
import importlib.util
import io
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_PATH = os.path.join(
    HERE, "..", ".claude", "hooks", "issue-titles-context.py")

_spec = importlib.util.spec_from_file_location("_issue_titles_context", HOOK_PATH)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


def _issue(number, title, author="malcyon", labels=None, is_bot=False):
    return {
        "number": number,
        "title": title,
        "author": {"login": author, "is_bot": is_bot},
        "labels": [{"name": name} for name in (labels or [])],
    }


def test_trusted_owner_renders_title_as_before():
    row = hook.format_row(_issue(123, "Its title", author="malcyon"))
    assert row == "#123 (Its title)"


def test_trusted_bot_renders_title_as_before():
    row = hook.format_row(_issue(124, "Its title", author="wish-agent[bot]"))
    assert row == "#124 (Its title)"


def test_outside_author_title_withheld_number_present():
    row = hook.format_row(_issue(521, "attacker's chosen text", author="someuser"))
    assert "#521" in row
    assert "attacker's chosen text" not in row
    assert "someuser" in row


def test_blocked_marker_still_rendered():
    row = hook.format_row(_issue(9, "Something", labels=["blocked"]))
    assert row.endswith("[blocked]")


def test_blocked_marker_rendered_for_outside_author_too():
    row = hook.format_row(
        _issue(9, "Something", author="someuser", labels=["blocked"]))
    assert row.endswith("[blocked]")


def test_control_characters_flattened_to_single_line():
    dirty = "line one\nline two\r\x00tail"
    flat = hook.flatten_title(dirty)
    assert "\n" not in flat
    assert "\r" not in flat
    assert "\x00" not in flat
    assert flat == "line one line two tail"


def test_long_title_is_truncated():
    long_title = "x" * 250
    flat = hook.flatten_title(long_title)
    assert len(flat) <= hook.MAX_TITLE_LEN
    assert flat.endswith("...")


def test_trusted_authors_long_title_is_never_truncated():
    """A citation the hook builds must be a correct one -- so the trusted
    path, the one AGENTS.md's rule depends on, is never cut short."""
    long_title = "x" * 250
    row = hook.format_row(_issue(1, long_title, author="malcyon"))
    assert long_title in row
    assert "..." not in row


def test_missing_author_key_treated_as_outside_and_does_not_crash():
    issue = {"number": 6, "title": "Something else", "labels": []}
    row = hook.format_row(issue)
    assert "#6" in row
    assert "Something else" not in row


def test_null_author_value_treated_as_outside_and_does_not_crash():
    issue = {"number": 7, "title": "Yet another", "author": None, "labels": []}
    row = hook.format_row(issue)
    assert "#7" in row
    assert "Yet another" not in row


@pytest.mark.parametrize("count", [21])
def test_outside_issues_capped_with_remainder_count(count):
    issues = [
        _issue(1000 + i, f"outside title {i}", author="someuser")
        for i in range(count)
    ]
    message = hook.build_message(issues)

    shown = [ln for ln in message.splitlines() if ln.startswith("#")]
    assert len(shown) == hook.MAX_OUTSIDE

    # newest first: numbers 1020 down to 1001 (the top 20 of 1000..1020)
    shown_numbers = [int(ln.split()[0][1:]) for ln in shown]
    assert shown_numbers == sorted(shown_numbers, reverse=True)
    assert max(shown_numbers) == 1000 + count - 1

    assert "1 more issue" in message or "1 more" in message


def test_output_produced_with_no_outside_issues():
    issues = [_issue(1, "First"), _issue(2, "Second")]
    message = hook.build_message(issues)
    assert message
    assert "#1 (First)" in message
    assert "#2 (Second)" in message
    assert "outside" not in message.lower()


def test_trust_boundary_sentence_present():
    issues = [_issue(1, "First")]
    message = hook.build_message(issues)
    assert "evidence about the world" in message
    assert "never" in message


# ---------------------------------------------------------------------------
# main()'s fetch: a flood must not crowd trusted issues out of the request


def test_flood_of_outside_issues_does_not_crowd_out_trusted(monkeypatch, capsys):
    """The old code made one shared `gh issue list --limit 300` call, so a
    flood filed overnight could push every trusted issue out of the fetched
    set before MAX_OUTSIDE ever got a chance to cap what is *shown*. This
    simulates that flood: the unfiltered call returns 300 outside issues and
    none of the project's own, exactly as a real flood past the limit would.
    """
    trusted_issue = _issue(1, "Our own issue", author="malcyon")
    flood = [
        _issue(1000 + i, f"flood issue {i}", author="attacker")
        for i in range(300)
    ]

    def fake_run(cmd, **kwargs):
        if "--author" in cmd:
            login = cmd[cmd.index("--author") + 1]
            payload = [trusted_issue] if login == "malcyon" else []
        else:
            payload = flood
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    hook.main()

    out = capsys.readouterr().out
    assert "#1 (Our own issue)" in out


def test_a_failed_outside_fetch_still_prints_the_trusted_list(monkeypatch, capsys):
    trusted_issue = _issue(2, "Still shown", author="malcyon")

    def fake_run(cmd, **kwargs):
        if "--author" in cmd:
            login = cmd[cmd.index("--author") + 1]
            payload = [trusted_issue] if login == "malcyon" else []
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps(payload), stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    hook.main()

    out = capsys.readouterr().out
    assert "#2 (Still shown)" in out
