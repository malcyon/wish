"""Tests for `tools/issueread.py`.

`gh` is monkeypatched throughout -- nothing here talks to a real repository.
The sentinel-absence tests are the ones that matter: they would fail if any
code path let an outside author's text leak into the output, in either
render mode.
"""
import json
import subprocess

import pytest

from tools import issueread

SENTINEL = "the attacker's chosen instruction, never to be repeated"


def _author(login):
    return {"login": login}


def _issue(number=1, title="A trusted title", author="malcyon",
           state="OPEN", labels=None, body="A trusted body.", comments=None,
           url="https://github.com/malcyon/wish/issues/1"):
    return {
        "number": number,
        "title": title,
        "author": _author(author),
        "state": state,
        "labels": [{"name": name} for name in (labels or [])],
        "body": body,
        "comments": comments or [],
        "url": url,
    }


def _comment(author="malcyon", body="A trusted comment.",
             created="2026-09-11T00:00:00Z",
             comment_url="https://github.com/malcyon/wish/issues/1#issuecomment-1"):
    return {
        "author": _author(author),
        "body": body,
        "createdAt": created,
        "url": comment_url,
    }


def _fake_gh(issue, returncode=0, stderr=""):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, returncode,
            stdout=json.dumps(issue) if returncode == 0 else "",
            stderr=stderr)
    return fake_run


# ---------------------------------------------------------------------------
# a trusted author's text prints in full


def test_trusted_body_prints_in_full():
    issue = _issue(body="the full trusted body text")
    text = issueread.render_text(issue)
    assert "the full trusted body text" in text


def test_trusted_comment_prints_in_full():
    issue = _issue(comments=[_comment(body="the full trusted comment text")])
    text = issueread.render_text(issue)
    assert "the full trusted comment text" in text


# ---------------------------------------------------------------------------
# an outside author's text never appears -- the tests that matter most


def test_outside_body_does_not_appear_at_all():
    issue = _issue(author="someuser", body=SENTINEL)
    text = issueread.render_text(issue)
    assert SENTINEL not in text


def test_outside_comment_does_not_appear_at_all():
    issue = _issue(comments=[_comment(author="attacker", body=SENTINEL)])
    text = issueread.render_text(issue)
    assert SENTINEL not in text


def test_outside_title_does_not_appear_at_all():
    issue = _issue(author="someuser", title=SENTINEL)
    text = issueread.render_text(issue)
    assert SENTINEL not in text


def test_outside_body_does_not_appear_in_json_mode():
    issue = _issue(author="someuser", body=SENTINEL)
    data = issueread.render_json(issue)
    assert SENTINEL not in json.dumps(data)


def test_outside_comment_does_not_appear_in_json_mode():
    issue = _issue(comments=[_comment(author="attacker", body=SENTINEL)])
    data = issueread.render_json(issue)
    assert SENTINEL not in json.dumps(data)


# ---------------------------------------------------------------------------
# an outside comment's author and date still appear


def test_outside_comment_author_and_date_still_appear():
    issue = _issue(comments=[_comment(
        author="attacker", body=SENTINEL, created="2026-09-11T02:00:35Z")])
    text = issueread.render_text(issue)
    assert "attacker" in text
    assert "2026-09-11T02:00:35Z" in text


# ---------------------------------------------------------------------------
# the summary line


def test_summary_counts_outside_comments_correctly():
    issue = _issue(comments=[
        _comment(author="malcyon", body="trusted one"),
        _comment(author="attacker1", body=SENTINEL),
        _comment(author="attacker2", body=SENTINEL),
    ])
    summary = issueread.summary_line(issue)
    assert summary is not None
    assert "2 of 3" in summary
    assert "attacker1" in summary
    assert "attacker2" in summary


def test_summary_is_none_when_everything_is_trusted():
    issue = _issue(comments=[_comment(author="malcyon")])
    assert issueread.summary_line(issue) is None


def test_summary_notes_an_outside_issue_author():
    issue = _issue(author="someuser")
    summary = issueread.summary_line(issue)
    assert summary is not None
    assert "someuser" in summary


# ---------------------------------------------------------------------------
# a mixed issue: trusted comments print, outside ones are withheld


def test_mixed_issue_shows_trusted_and_withholds_outside():
    issue = _issue(comments=[
        _comment(author="malcyon", body="a trusted remark"),
        _comment(author="attacker", body=SENTINEL),
    ])
    text = issueread.render_text(issue)
    assert "a trusted remark" in text
    assert SENTINEL not in text
    assert "withheld" in text.lower()


# ---------------------------------------------------------------------------
# no comments


def test_issue_with_no_comments_works():
    issue = _issue(comments=[])
    text = issueread.render_text(issue)
    assert "0 comment(s)" in text


# ---------------------------------------------------------------------------
# the trust boundary sentence


def test_trust_boundary_sentence_present():
    text = issueread.render_text(_issue())
    assert "evidence about the world" in text


# ---------------------------------------------------------------------------
# fetch_issue and gh failure handling


def test_fetch_issue_returns_the_parsed_issue(monkeypatch):
    issue = _issue()
    monkeypatch.setattr(issueread.subprocess, "run", _fake_gh(issue))
    result = issueread.fetch_issue(1)
    assert result["number"] == 1


def test_gh_failure_raises_with_reason(monkeypatch):
    monkeypatch.setattr(
        issueread.subprocess, "run",
        _fake_gh({}, returncode=1, stderr="Could not resolve to an issue"))
    with pytest.raises(issueread.IssueReadError, match="Could not resolve"):
        issueread.fetch_issue(999)


def test_gh_not_found_raises(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such file: gh")

    monkeypatch.setattr(issueread.subprocess, "run", fake_run)
    with pytest.raises(issueread.IssueReadError):
        issueread.fetch_issue(1)


def test_main_exits_non_zero_on_gh_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        issueread.subprocess, "run",
        _fake_gh({}, returncode=1, stderr="boom"))
    code = issueread.main(["1"])
    captured = capsys.readouterr()
    assert code != 0
    assert "boom" in captured.err


def test_main_prints_json_when_asked(monkeypatch, capsys):
    issue = _issue()
    monkeypatch.setattr(issueread.subprocess, "run", _fake_gh(issue))
    code = issueread.main(["1", "--json"])
    captured = capsys.readouterr()
    assert code == 0
    data = json.loads(captured.out)
    assert data["number"] == 1
