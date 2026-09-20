"""Tests for tools/wishagent.py. Nothing here touches the network -- every
test replaces `wishagent._request`, the single function that would.
"""

import io
import json
import os
import re
import sys
import time
import urllib.error

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import tools.wishagent as wishagent  # noqa: E402

WINDOWS = os.name == "nt"


def _rsa_key_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture
def key_file(tmp_path):
    path = tmp_path / "private-key.pem"
    path.write_bytes(_rsa_key_pem())
    os.chmod(path, 0o600)
    return path


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Every test names its own configuration; none reads the real machine."""
    for name in (
        "WISH_AGENT_KEY",
        "WISH_AGENT_APP_ID",
        "WISH_AGENT_INSTALLATION_ID",
        "WISH_AGENT_REPO",
    ):
        monkeypatch.delenv(name, raising=False)
    wishagent._token_cache["token"] = None
    wishagent._token_cache["expires_at"] = 0.0
    yield
    wishagent._token_cache["token"] = None
    wishagent._token_cache["expires_at"] = 0.0


@pytest.fixture
def configured(monkeypatch, key_file):
    monkeypatch.setenv("WISH_AGENT_KEY", str(key_file))
    monkeypatch.setenv("WISH_AGENT_APP_ID", "12345")
    monkeypatch.setenv("WISH_AGENT_INSTALLATION_ID", "67890")
    return key_file


def _install_fake_transport(monkeypatch, responses):
    """`responses` is a list of (status, body_dict) popped one per call, or
    a single (status, body_dict) reused for every call. Returns the list of
    (method, url, headers, body) calls actually made.
    """
    calls = []
    single = isinstance(responses, tuple)

    def fake_request(method, url, headers, body):
        calls.append((method, url, dict(headers), body))
        status, payload = responses if single else responses[len(calls) - 1]
        raw = json.dumps(payload).encode("utf-8") if payload is not None else b""
        return status, {}, raw

    monkeypatch.setattr(wishagent, "_request", fake_request)
    return calls


def _prime_token_cache():
    wishagent._token_cache["token"] = "sentinel-installation-token"
    wishagent._token_cache["expires_at"] = 9999999999.0


# ---------------------------------------------------------------------------
# JWT


def test_jwt_carries_app_id_and_a_window_under_the_600s_ceiling(configured):
    token = wishagent.make_jwt()
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload["iss"] == "12345"
    assert payload["exp"] - payload["iat"] < 600


def test_jwt_iat_is_backdated_by_the_clock_skew_constant(configured):
    before = int(time.time())
    token = wishagent.make_jwt()
    after = int(time.time())
    payload = jwt.decode(token, options={"verify_signature": False})

    # `iat` must sit close to `now - IAT_SKEW_SECONDS`, not just leave a gap
    # under 600s to `exp` -- a test that only checked the gap would still
    # pass with the backdating deleted entirely.
    assert before - wishagent.IAT_SKEW_SECONDS - 2 <= payload["iat"]
    assert payload["iat"] <= after - wishagent.IAT_SKEW_SECONDS + 2


# ---------------------------------------------------------------------------
# Key file safety


@pytest.mark.skipif(WINDOWS, reason="file mode bits do not mean this on Windows")
def test_group_readable_key_is_refused(monkeypatch, tmp_path):
    path = tmp_path / "private-key.pem"
    path.write_bytes(_rsa_key_pem())
    os.chmod(path, 0o644)
    monkeypatch.setenv("WISH_AGENT_KEY", str(path))
    monkeypatch.setenv("WISH_AGENT_APP_ID", "1")

    with pytest.raises(wishagent.ConfigError, match="chmod"):
        wishagent.make_jwt()


@pytest.mark.skipif(WINDOWS, reason="file mode bits do not mean this on Windows")
def test_missing_key_is_refused_naming_the_path(monkeypatch, tmp_path):
    path = tmp_path / "does-not-exist.pem"
    monkeypatch.setenv("WISH_AGENT_KEY", str(path))
    monkeypatch.setenv("WISH_AGENT_APP_ID", "1")

    with pytest.raises(wishagent.ConfigError, match=re.escape(str(path))):
        wishagent.make_jwt()


# ---------------------------------------------------------------------------
# The token never appears in output


@pytest.mark.parametrize(
    "invoke",
    [
        lambda: wishagent.create_issue("title", "body"),
        lambda: wishagent.comment_on_issue(1, "body"),
        lambda: wishagent.close_issue(1),
        lambda: wishagent.label_issue(1, add=["bug"]),
        lambda: wishagent.edit_issue(1, title="t"),
    ],
)
def test_token_never_appears_in_output(capsys, monkeypatch, invoke):
    _prime_token_cache()
    _install_fake_transport(
        monkeypatch, (200, {"number": 1, "html_url": "http://example", "state": "closed"})
    )

    invoke()

    captured = capsys.readouterr()
    assert "sentinel-installation-token" not in captured.out
    assert "sentinel-installation-token" not in captured.err


# ---------------------------------------------------------------------------
# edit_issue sends only the fields it was given


@pytest.mark.parametrize(
    "kwargs, expected_body",
    [
        ({"title": "corrected title"}, {"title": "corrected title"}),
        ({"body_text": "corrected body"}, {"body": "corrected body"}),
        (
            {"title": "corrected title", "body_text": "corrected body"},
            {"title": "corrected title", "body": "corrected body"},
        ),
    ],
)
def test_edit_sends_only_the_fields_it_was_given(monkeypatch, kwargs, expected_body):
    """A version that always sent both fields would silently overwrite
    whichever one the caller did not mean to touch -- the single-field cases
    are the point of this test, not the two-field one."""
    _prime_token_cache()
    calls = _install_fake_transport(monkeypatch, (200, {"html_url": "http://example"}))

    wishagent.edit_issue(1, **kwargs)

    assert len(calls) == 1
    method, url, _headers, body = calls[0]
    assert method == "PATCH"
    assert url.endswith("/issues/1")
    assert body == expected_body


def test_edit_without_a_field_is_a_usage_error(monkeypatch):
    calls = _install_fake_transport(monkeypatch, (200, {"html_url": "http://example"}))

    with pytest.raises(SystemExit) as excinfo:
        wishagent.main(["edit", "1"])

    assert excinfo.value.code == 2
    assert calls == []


def test_edit_posts_its_comment_after_the_patch(monkeypatch):
    _prime_token_cache()
    calls = _install_fake_transport(
        monkeypatch,
        [
            (200, {"html_url": "http://example/issues/1"}),
            (200, {"html_url": "http://example/issues/1#comment"}),
        ],
    )

    wishagent.edit_issue(1, title="corrected title", comment_text="I corrected it.")

    assert len(calls) == 2
    method, url, _headers, _body = calls[0]
    assert method == "PATCH"
    assert url.endswith("/issues/1")
    method, url, _headers, _body = calls[1]
    assert method == "POST"
    assert url.endswith("/issues/1/comments")


def test_reopen_sets_the_state_to_open_and_says_so(monkeypatch, capsys):
    _prime_token_cache()
    calls = _install_fake_transport(monkeypatch, (200, {"state": "open"}))

    assert wishagent.main(["reopen", "7"]) == 0

    assert len(calls) == 1
    method, url, _headers, body = calls[0]
    assert method == "PATCH"
    assert url.endswith("/issues/7")
    assert body == {"state": "open"}
    assert capsys.readouterr().out.strip() == "reopened #7"


def test_reopen_posts_its_comment_after_the_state_change(monkeypatch, tmp_path):
    _prime_token_cache()
    comment = tmp_path / "why.md"
    comment.write_text("Reopened because the fix regressed.", encoding="utf-8")
    calls = _install_fake_transport(
        monkeypatch,
        [
            (200, {"state": "open"}),
            (201, {"html_url": "http://example/issues/7#comment"}),
        ],
    )

    assert wishagent.main(["reopen", "7", "--comment-file", str(comment)]) == 0

    assert [(c[0], c[1].rsplit("/issues/", 1)[1]) for c in calls] == [
        ("PATCH", "7"),
        ("POST", "7/comments"),
    ]
    assert calls[0][3] == {"state": "open"}
    assert calls[1][3] == {"body": "Reopened because the fix regressed."}


def test_a_failed_reopen_posts_no_comment(monkeypatch, tmp_path, capsys):
    _prime_token_cache()
    comment = tmp_path / "why.md"
    comment.write_text("Reopened.", encoding="utf-8")
    calls = _install_fake_transport(monkeypatch, (404, {"message": "Not Found"}))

    assert wishagent.main(["reopen", "7", "--comment-file", str(comment)]) == 1

    assert [c[0] for c in calls] == ["PATCH"]
    captured = capsys.readouterr()
    assert "reopened" not in captured.out
    assert "404" in captured.err


def test_a_reopen_whose_comment_fails_leaves_the_issue_reopened(
        monkeypatch, tmp_path, capsys):
    _prime_token_cache()
    comment = tmp_path / "why.md"
    comment.write_text("Reopened.", encoding="utf-8")
    calls = _install_fake_transport(
        monkeypatch,
        [(200, {"state": "open"}), (422, {"message": "Validation Failed"})],
    )

    assert wishagent.main(["reopen", "7", "--comment-file", str(comment)]) == 1

    assert [c[0] for c in calls] == ["PATCH", "POST"]
    assert calls[0][3] == {"state": "open"}
    captured = capsys.readouterr()
    assert "reopened" not in captured.out
    assert "422 commenting on #7" in captured.err


# ---------------------------------------------------------------------------
# Installation token minting


def test_token_request_body_is_exactly_the_narrowed_scope(monkeypatch, configured):
    calls = _install_fake_transport(
        monkeypatch,
        (200, {"token": "abc123", "expires_at": "2099-01-01T00:00:00Z"}),
    )

    wishagent.get_installation_token()

    assert len(calls) == 1
    _method, _url, _headers, body = calls[0]
    assert body == {"repositories": ["wish"], "permissions": {"issues": "write"}}


# ---------------------------------------------------------------------------
# Retry behaviour


def test_403_is_not_retried(monkeypatch):
    _prime_token_cache()
    calls = _install_fake_transport(monkeypatch, (403, {"message": "Forbidden"}))

    with pytest.raises(wishagent.ApiError):
        wishagent.comment_on_issue(1, "body")

    assert len(calls) == 1


def test_5xx_is_retried_then_succeeds(monkeypatch):
    _prime_token_cache()
    monkeypatch.setattr(wishagent.time, "sleep", lambda _seconds: None)
    calls = _install_fake_transport(
        monkeypatch,
        [
            (500, {"message": "Internal Server Error"}),
            (500, {"message": "Internal Server Error"}),
            (200, {"html_url": "http://example"}),
        ],
    )

    wishagent.comment_on_issue(1, "body")

    assert len(calls) == 3


def test_5xx_stops_after_the_retry_bound(monkeypatch):
    _prime_token_cache()
    monkeypatch.setattr(wishagent.time, "sleep", lambda _seconds: None)
    calls = _install_fake_transport(monkeypatch, (500, {"message": "Internal Server Error"}))

    with pytest.raises(wishagent.ApiError):
        wishagent.comment_on_issue(1, "body")

    assert len(calls) == 1 + wishagent.MAX_5XX_RETRIES


# ---------------------------------------------------------------------------
# Label removal percent-encodes its name


def test_label_remove_percent_encodes_a_space(monkeypatch):
    _prime_token_cache()
    calls = _install_fake_transport(monkeypatch, (200, None))

    wishagent.label_issue(1, remove=["Priority: Medium"])

    assert len(calls) == 1
    method, url, _headers, _body = calls[0]
    assert method == "DELETE"
    assert url.endswith("/labels/Priority%3A%20Medium")


# ---------------------------------------------------------------------------
# Connection-level failures: no status code for _call's retry to inspect


def test_request_passes_a_bounded_timeout_to_urlopen(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        raise urllib.error.URLError("stop here, the timeout was already seen")

    monkeypatch.setattr(wishagent.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(wishagent.ApiError):
        wishagent._request("GET", "http://example", {}, None)

    assert seen["timeout"] == wishagent.REQUEST_TIMEOUT


def test_url_error_from_urlopen_becomes_api_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(wishagent.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(wishagent.ApiError):
        wishagent._request("GET", "http://example", {}, None)


def test_bare_os_error_from_urlopen_becomes_api_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise ConnectionResetError("connection reset by peer")

    monkeypatch.setattr(wishagent.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(wishagent.ApiError):
        wishagent._request("GET", "http://example", {}, None)


def test_connection_failure_is_not_retried(monkeypatch):
    """`_call`'s retry loop inspects a status code a connection failure never
    has, so this fails on the first attempt rather than looping."""
    _prime_token_cache()
    attempts = []

    def fake_request(method, url, headers, body):
        attempts.append(1)
        raise wishagent.ApiError("boom")

    monkeypatch.setattr(wishagent, "_request", fake_request)

    with pytest.raises(wishagent.ApiError):
        wishagent.comment_on_issue(1, "body")

    assert len(attempts) == 1


# ---------------------------------------------------------------------------
# A malformed config.json is reported, not left to crash


def test_malformed_config_json_raises_config_error_naming_the_path(monkeypatch, tmp_path):
    bad = tmp_path / "config.json"
    bad.write_text("{not valid json")
    monkeypatch.setattr(wishagent, "CONFIG_PATH", str(bad))

    with pytest.raises(wishagent.ConfigError, match=re.escape(str(bad))):
        wishagent._config_json()


# ---------------------------------------------------------------------------
# repo() treats an empty environment variable like its siblings do


def test_repo_empty_env_var_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("WISH_AGENT_REPO", "")
    assert wishagent.repo() == wishagent.DEFAULT_REPO


# ---------------------------------------------------------------------------
# Push mode: a token that can push, and a git credential helper built on it

TOKEN_REPLY = {"token": "push-token-abc", "expires_at": "2099-01-01T00:00:00Z"}


def test_push_token_asks_for_contents_and_workflows_write_on_this_repository(
    monkeypatch, configured
):
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    token = wishagent.get_push_token()

    assert token == "push-token-abc"
    method, url, _headers, body = calls[0]
    assert method == "POST"
    assert url.endswith("/app/installations/67890/access_tokens")
    assert body == {
        "repositories": ["wish"],
        "permissions": {"contents": "write", "workflows": "write"},
    }


def test_the_issues_token_still_asks_for_issues_write_and_nothing_more(
    monkeypatch, configured
):
    """The push mode was added beside this one, not into it: an issues token
    that quietly gained `contents: write` could rewrite the repository."""
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    wishagent.get_installation_token()

    assert calls[0][3]["permissions"] == {"issues": "write"}


def test_a_push_token_is_minted_on_every_call_and_cached_nowhere(
    monkeypatch, configured
):
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    wishagent.get_push_token()
    wishagent.get_push_token()

    assert len(calls) == 2
    assert wishagent._token_cache["token"] is None


def test_the_push_token_leaves_the_issues_token_cache_alone(monkeypatch, configured):
    _prime_token_cache()
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    assert wishagent.get_push_token() == "push-token-abc"
    assert wishagent._token_cache["token"] == "sentinel-installation-token"

    # ...and the issues mode still takes the cached one without a call.
    calls.clear()
    assert wishagent.get_installation_token() == "sentinel-installation-token"
    assert calls == []


def test_a_push_token_is_written_to_no_file(monkeypatch, configured):
    """The point of a helper that mints per request is that no token exists at
    rest. Any open for writing, appending or creating, anywhere, fails the run:
    watching one directory would miss a write to the real config directory, to
    /tmp, or to a path this test did not think of."""
    import builtins

    real_open = builtins.open
    writes = []

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in "wax+"):
            writes.append(str(file))
            raise AssertionError(f"opened {file!r} for writing")
        return real_open(file, mode, *args, **kwargs)

    _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))
    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)

    wishagent.get_push_token()
    wishagent.answer_git_credential("get", "protocol=https\nhost=github.com\n\n")

    assert writes == []


def test_push_token_command_prints_only_the_token(monkeypatch, configured, capsys):
    _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    assert wishagent.main(["push-token"]) == 0

    assert capsys.readouterr().out == "push-token-abc\n"


@pytest.mark.parametrize("status, wording", [(401, "clock"), (404, "not installed")])
def test_push_mode_fails_as_plainly_as_the_issues_mode(
    monkeypatch, configured, capsys, status, wording
):
    _install_fake_transport(monkeypatch, (status, {"message": "nope"}))

    assert wishagent.main(["push-token"]) == 1

    captured = capsys.readouterr()
    assert wording in captured.err
    assert captured.out == ""


def _credential(monkeypatch, action, request):
    monkeypatch.setattr(sys, "stdin", io.StringIO(request))
    return wishagent.main(["git-credential", action])


def test_git_credential_get_answers_github_with_x_access_token_and_a_fresh_token(
    monkeypatch, configured, capsys
):
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    rc = _credential(monkeypatch, "get", "protocol=https\nhost=github.com\n\n")

    assert rc == 0
    assert capsys.readouterr().out == "username=x-access-token\npassword=push-token-abc\n"
    assert calls[0][3]["permissions"] == {"contents": "write", "workflows": "write"}


def test_git_credential_get_mints_a_token_per_request(monkeypatch, configured, capsys):
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    _credential(monkeypatch, "get", "protocol=https\nhost=github.com\n\n")
    _credential(monkeypatch, "get", "protocol=https\nhost=github.com\n\n")

    assert len(calls) == 2


@pytest.mark.parametrize(
    "request_text",
    [
        "protocol=https\nhost=gitlab.com\n\n",
        "protocol=https\nhost=github.com.evil.example\n\n",
        "protocol=https\nhost=github.com:443\n\n",
        "protocol=http\nhost=github.com\n\n",
        "protocol=ssh\nhost=github.com\n\n",
        # A request that does not say https is not answered as if it had.
        "host=github.com\n\n",
        "",
    ],
)
def test_git_credential_answers_nobody_but_github_over_https(
    monkeypatch, configured, capsys, request_text
):
    """A token that can push must not be offered to any other host, or to a
    plaintext one: no answer lets git ask whichever helper is next."""
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    rc = _credential(monkeypatch, "get", request_text)

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert calls == []


@pytest.mark.parametrize("action", ["store", "erase"])
def test_git_credential_store_and_erase_do_nothing(
    monkeypatch, configured, capsys, action
):
    """git offers back what it was given after a successful push. Nothing is
    kept, so there is nothing to store or erase, and no call to make."""
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    rc = _credential(
        monkeypatch, action,
        "protocol=https\nhost=github.com\nusername=x-access-token\npassword=whatever\n\n",
    )

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert calls == []


def test_git_credential_reads_only_up_to_the_blank_line(monkeypatch, configured, capsys):
    """The protocol ends a request with a blank line; what follows is not part
    of it, and a host smuggled in after it must not be believed."""
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    _credential(monkeypatch, "get", "protocol=https\nhost=gitlab.com\n\nhost=github.com\n")

    assert capsys.readouterr().out == ""
    assert calls == []


def test_git_credential_failure_prints_no_answer_and_says_why(
    monkeypatch, configured, capsys
):
    _install_fake_transport(monkeypatch, (401, {"message": "Bad credentials"}))

    rc = _credential(monkeypatch, "get", "protocol=https\nhost=github.com\n\n")

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "401" in captured.err


@pytest.mark.parametrize(
    "separator",
    ["\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"],
)
def test_git_credential_splits_lines_on_newline_only(
    monkeypatch, configured, capsys, separator
):
    """`str.splitlines()` splits on all of these, and git passes them through
    inside a value. A user name of `a<sep>host=github.com` on a URL for another
    host would then carry a later `host=` past the real one and be answered
    with a push token."""
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))
    request = f"protocol=https\nhost=evil.example\nusername=a{separator}host=github.com\n\n"

    rc = _credential(monkeypatch, "get", request)

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert calls == []


def test_git_credential_ignores_an_action_it_does_not_know(
    monkeypatch, configured, capsys
):
    """git's credential protocol asks a helper to ignore an action it does not
    know, not to fail with a usage error."""
    calls = _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    rc = _credential(monkeypatch, "some-future-action", "protocol=https\nhost=github.com\n\n")

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert calls == []


def test_git_credential_with_no_action_defaults_to_get(monkeypatch, configured, capsys):
    _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))
    monkeypatch.setattr(sys, "stdin", io.StringIO("protocol=https\nhost=github.com\n\n"))

    rc = wishagent.main(["git-credential"])

    assert rc == 0
    assert "password=push-token-abc" in capsys.readouterr().out


def test_git_credential_reports_a_server_error_and_answers_nothing(
    monkeypatch, configured, capsys
):
    _install_fake_transport(monkeypatch, (500, {"message": "boom"}))
    monkeypatch.setattr(wishagent.time, "sleep", lambda _seconds: None)

    rc = _credential(monkeypatch, "get", "protocol=https\nhost=github.com\n\n")

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "500" in captured.err


def test_the_push_token_is_printed_only_where_it_was_asked_for(
    monkeypatch, configured, capsys
):
    """It reaches stdout in the two places that exist to print it, exactly
    once each, and nothing reaches stderr."""
    _install_fake_transport(monkeypatch, (201, TOKEN_REPLY))

    wishagent.main(["push-token"])
    first = capsys.readouterr()
    _credential(monkeypatch, "get", "protocol=https\nhost=github.com\n\n")
    second = capsys.readouterr()

    assert first.out == "push-token-abc\n" and first.err == ""
    assert second.out.count("push-token-abc") == 1 and second.err == ""
