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
import os

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
