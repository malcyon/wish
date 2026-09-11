"""Tests for tools/wishagent.py. Nothing here touches the network -- every
test replaces `wishagent._request`, the single function that would.
"""

import json
import os
import sys

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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

    with pytest.raises(wishagent.ConfigError, match=str(path)):
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
