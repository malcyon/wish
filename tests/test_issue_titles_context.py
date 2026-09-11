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


def test_a_trusted_authors_long_title_is_never_truncated():
    """A citation the hook builds must be a correct one -- so the trusted
    path, the one AGENTS.md's rule depends on, is never cut short.
    Truncation was removed with `MAX_TITLE_LEN`; a title is always cited in
    full now, however long."""
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


def test_a_flood_of_outside_issues_does_not_crowd_out_trusted(monkeypatch, capsys):
    """One `gh issue list --limit 1000` call now does the whole fetch, and
    `build_message` splits trusted from outside afterwards -- so a flood
    that fits inside that limit, however large, cannot push the project's
    own issue out of the set `build_message` sees, which is what a two-call
    design used to need a loop to guarantee."""
    trusted_issue = _issue(1, "Our own issue", author="malcyon")
    flood = [
        _issue(1000 + i, f"flood issue {i}", author="attacker")
        for i in range(300)
    ]

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps([trusted_issue, *flood]), stderr="")

    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    hook.main()

    out = capsys.readouterr().out
    assert "#1 (Our own issue)" in out


def test_a_failed_fetch_prints_nothing_rather_than_blocking(monkeypatch, capsys):
    """One call now does the whole fetch, so there is only one way for it to
    fail -- and failing here means the session starts with no issue list at
    all, the same silent-failure contract as an offline or unauthenticated
    `gh` everywhere else in this hook."""
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    result = hook.main()

    out = capsys.readouterr().out
    assert result == 0
    assert out == ""


def test_missing_ghtrust_module_exits_0_printing_nothing(monkeypatch, capsys):
    """`tools/ghtrust.py` not being findable or importable must never be
    the thing that breaks somebody starting work -- same silent-failure
    contract as an unauthenticated or offline `gh`.

    `gh` is monkeypatched too, to an outside issue: with `ghtrust` gone,
    `main()`'s own filtering would otherwise call `ghtrust.is_trusted` on a
    real result and crash with an `AttributeError` rather than exiting
    cleanly -- which is exactly the failure this guards against, and why the
    fetch cannot be left to return an empty list by accident.
    """
    outside_issue = _issue(521, "Something", author="someuser")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps([outside_issue]), stderr="")

    monkeypatch.setattr(hook, "ghtrust", None)
    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    result = hook.main()

    out = capsys.readouterr().out
    assert result == 0
    assert out == ""
