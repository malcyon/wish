"""Tests for `tools/ghtrust.py`.

`is_trusted` decides which authors go into an agent's context in full and
which get withheld; `flatten` and `withheld` are the shared scrubbing and
wording both `.claude/hooks/issue-titles-context.py` and
`tools/issueread.py` rest on. Everything here is pure and needs no `gh`.
"""
import re

from tools import ghtrust

# ---------------------------------------------------------------------------
# is_trusted


def test_is_trusted_for_repository_owner():
    assert ghtrust.is_trusted({"login": "malcyon"})


# `gh` spells the project's own bot three different ways depending on the
# route -- measured live against malcyon/wish on 2026-09-11, with a real
# issue opened and commented on by the `wish-agent` App installation. The
# first version of `is_trusted` recognised only the first of these, so it
# trusted none of the spellings `gh` actually hands back.


def test_is_trusted_for_the_bots_rest_api_spelling():
    """`POST /issues`'s response, `user.login`."""
    assert ghtrust.is_trusted({"login": "wish-agent[bot]"})


def test_is_trusted_for_the_bots_gh_issue_view_spelling():
    """`gh issue view N --json author`."""
    assert ghtrust.is_trusted({"is_bot": True, "login": "app/wish-agent"})


def test_is_trusted_for_the_bots_bare_comment_author_spelling():
    """`gh issue view N --json comments`, each comment's own `author`."""
    assert ghtrust.is_trusted({"login": "wish-agent"})


def test_is_trusted_false_for_an_outside_account():
    assert not ghtrust.is_trusted({"login": "someuser"})


def test_is_trusted_false_for_none():
    """`gh`'s `--json author` is `None` for an account since deleted."""
    assert not ghtrust.is_trusted(None)


def test_is_trusted_false_for_a_missing_login_key():
    assert not ghtrust.is_trusted({})


def test_is_trusted_false_for_a_login_differing_only_in_case():
    """GitHub logins are case-insensitive for logging in, but nobody has
    decided this project should widen the comparison -- so an exact,
    case-sensitive match is the conservative reading."""
    assert not ghtrust.is_trusted({"login": "Malcyon"})
    assert not ghtrust.is_trusted({"login": "MALCYON"})


def test_is_trusted_false_for_a_non_dict():
    assert not ghtrust.is_trusted("malcyon")
    assert not ghtrust.is_trusted(123)


def test_is_bot_alone_does_not_trust_a_differently_named_app():
    """Any GitHub App commenting here carries `is_bot: true`, ours included
    -- so the flag says nothing about *which* App this is, and trust has to
    turn on the name instead."""
    assert not ghtrust.is_trusted({"is_bot": True, "login": "app/some-other-app"})
    assert not ghtrust.is_trusted({"is_bot": True, "login": "some-other-app[bot]"})


def test_normalising_the_bots_wrapper_does_not_widen_trust_to_the_owners_name():
    """Stripping `app/` and `[bot]` must only ever produce evidence of *the
    bot*, never of the owner -- `malcyon` never legitimately appears wrapped
    this way, so a wrapped login that reduces to `malcyon` is a different
    actor (an unrelated App whose slug happens to be `malcyon`), not the
    repository owner, and must not be trusted."""
    assert not ghtrust.is_trusted({"login": "app/malcyon"})
    assert not ghtrust.is_trusted({"login": "malcyon[bot]"})


def test_a_wrapped_login_could_not_have_come_from_a_persons_own_username():
    """The reasoning that makes stripping `app/` and `[bot]` safe: GitHub
    restricts a username someone chooses to letters, digits and single
    hyphens, so a login carrying `/` or `[` was never typed in by a person
    signing up -- it is always `gh`'s own rendering of a bot or App actor.
    This is the premise `_strip_bot_wrapper` rests on; assert it here so a
    future edit that widens the allowed username characters cannot silently
    make that premise false."""
    username_chars = re.compile(r"^[A-Za-z0-9-]+$")
    assert not username_chars.match("app/malcyon")
    assert not username_chars.match("malcyon[bot]")


# ---------------------------------------------------------------------------
# flatten


def test_flatten_replaces_c0_controls_with_a_space():
    flat = ghtrust.flatten("a\tb\x01c\x1fd")
    assert flat == "a b c d"


def test_flatten_replaces_del_with_a_space():
    flat = ghtrust.flatten("a\x7fb")
    assert flat == "a b"


def test_flatten_collapses_a_newline_and_strips():
    flat = ghtrust.flatten("  line one\nline two  ")
    assert flat == "line one line two"


def test_flatten_never_truncates():
    """Truncation was removed with the `max_length` parameter -- a title is
    always cited in full, per AGENTS.md's rule."""
    long_text = "x" * 500
    assert ghtrust.flatten(long_text) == long_text


def test_flatten_none_is_empty_string():
    assert ghtrust.flatten(None) == ""


# ---------------------------------------------------------------------------
# scrub_body


def test_scrub_body_keeps_newlines():
    """Unlike `flatten`, a body or comment keeps its line structure -- an
    issue body here is Markdown with headings, lists and tables in it."""
    scrubbed = ghtrust.scrub_body("line one\nline two")
    assert scrubbed == "line one\nline two"


def test_scrub_body_replaces_a_tab_with_a_space():
    assert ghtrust.scrub_body("a\tb") == "a b"


def test_scrub_body_replaces_other_c0_controls_and_del_with_a_space():
    scrubbed = ghtrust.scrub_body("a\x01b\x1fc\x7fd")
    assert scrubbed == "a b c d"


def test_scrub_body_does_not_collapse_or_strip_whitespace():
    """Unlike `flatten`, nothing here is collapsed to one line or trimmed --
    a hex dump or an indented code block keeps its own spacing."""
    scrubbed = ghtrust.scrub_body("  line one\n\n  line two  ")
    assert scrubbed == "  line one\n\n  line two  "


def test_scrub_body_never_truncates():
    long_text = "x" * 5000
    assert ghtrust.scrub_body(long_text) == long_text


def test_scrub_body_none_is_empty_string():
    assert ghtrust.scrub_body(None) == ""


# ---------------------------------------------------------------------------
# withheld


def test_withheld_names_the_author_and_the_length():
    text = ghtrust.withheld(
        "comment", author="someuser", length=42, where="gh issue view 5")
    assert "someuser" in text
    assert "42" in text
    assert "gh issue view 5" in text
    assert "comment" in text


def test_withheld_does_not_contain_the_withheld_text_itself():
    secret = "the attacker's chosen instruction"
    text = ghtrust.withheld(
        "body", author="someuser", length=len(secret), where="gh issue view 5")
    assert secret not in text


def test_withheld_singular_for_one_character():
    text = ghtrust.withheld(
        "title", author="someuser", length=1, where="gh issue view 5")
    assert "1 character;" in text or "1 character)" in text
    assert "1 characters" not in text


def test_withheld_names_an_unknown_account_when_author_is_falsy():
    text = ghtrust.withheld("title", author=None, length=3, where="gh issue view 5")
    assert "account" in text
