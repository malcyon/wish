"""Tests for `tools/ghtrust.py`.

`is_trusted` decides which authors go into an agent's context in full and
which get withheld; `flatten` and `withheld` are the shared scrubbing and
wording both `.claude/hooks/issue-titles-context.py` and
`tools/issueread.py` rest on. Everything here is pure and needs no `gh`.
"""
from tools import ghtrust

# ---------------------------------------------------------------------------
# is_trusted


def test_is_trusted_for_repository_owner():
    assert ghtrust.is_trusted({"login": "malcyon"})


def test_is_trusted_for_the_projects_own_bot():
    assert ghtrust.is_trusted({"login": "wish-agent[bot]"})


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


def test_flatten_with_no_max_length_never_truncates():
    long_text = "x" * 500
    assert ghtrust.flatten(long_text) == long_text


def test_flatten_with_max_length_truncates_with_an_ellipsis():
    long_text = "x" * 500
    flat = ghtrust.flatten(long_text, max_length=50)
    assert len(flat) <= 50
    assert flat.endswith("...")


def test_flatten_with_max_length_leaves_short_text_untouched():
    assert ghtrust.flatten("short", max_length=50) == "short"


def test_flatten_none_is_empty_string():
    assert ghtrust.flatten(None) == ""


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
