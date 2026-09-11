#!/usr/bin/env python3
"""Speak to GitHub as the `wish-agent` App, not as Donald's own account.

    tools/wishagent.py whoami
    tools/wishagent.py token
    tools/wishagent.py create  --title T --body-file F [--label L]...
    tools/wishagent.py comment N --body-file F
    tools/wishagent.py close   N [--comment-file F]
    tools/wishagent.py label   N [--add L]... [--remove L]...
    tools/wishagent.py edit-comment ID --body-file F

An issue or comment filed by an agent should say so in its byline, and a
GitHub App is how that happens without handing an agent Donald's own
credentials: `wish-agent[bot]` is the author instead of him. This mints the
App's short-lived JWT, exchanges it for an installation token scoped to
`issues: write` on this one repository, and makes the REST call -- never
GraphQL, and never `gh issue`'s own sub-commands, which resolve labels
through GraphQL where an installation token is accepted unevenly.

Configuration, each resolved in order, first hit wins:

* private key -- `$WISH_AGENT_KEY`, else `~/.config/wish-agent/private-key.pem`
* app id -- `$WISH_AGENT_APP_ID`, else `app_id` in `~/.config/wish-agent/config.json`
* installation id -- `$WISH_AGENT_INSTALLATION_ID`, else `installation_id` in that file
* repository -- `$WISH_AGENT_REPO`, else `malcyon/wish`

`config.json` holds two integers that already appear in GitHub URLs, so it is
not a secret and lives beside the key rather than in this repository.
"""

import argparse
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import jwt

API = "https://api.github.com"
DEFAULT_REPO = "malcyon/wish"
CONFIG_DIR = os.path.expanduser(os.path.join("~", ".config", "wish-agent"))
DEFAULT_KEY_PATH = os.path.join(CONFIG_DIR, "private-key.pem")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# GitHub refuses a JWT whose (exp - iat) exceeds 600 seconds. 60 seconds of
# slack behind `now` covers clock skew on the side that checks `iat`; the
# 500-second reach forward stays comfortably under the ceiling once that
# 60 is added back in, rather than landing on it exactly.
IAT_SKEW_SECONDS = 60
EXP_AHEAD_SECONDS = 500
MAX_5XX_RETRIES = 2

# Populated by get_installation_token() and read by nothing else; an
# installation token lives an hour and one process invocation lives seconds,
# so there is nothing to gain from writing it anywhere durable.
_token_cache = {"token": None, "expires_at": 0.0}


class ConfigError(Exception):
    """A required setting is missing, or the key file is unsafe to use."""


class ApiError(Exception):
    """GitHub answered a call with an error status."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Configuration


def _config_json():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def key_path():
    return os.environ.get("WISH_AGENT_KEY", DEFAULT_KEY_PATH)


def app_id():
    value = os.environ.get("WISH_AGENT_APP_ID")
    if value:
        return value
    value = _config_json().get("app_id")
    if value:
        return str(value)
    raise ConfigError(
        "No App ID configured. Set $WISH_AGENT_APP_ID, or put "
        f'"app_id" in {CONFIG_PATH}.'
    )


def installation_id():
    value = os.environ.get("WISH_AGENT_INSTALLATION_ID")
    if value:
        return value
    value = _config_json().get("installation_id")
    if value:
        return str(value)
    raise ConfigError(
        "No installation ID configured. Set $WISH_AGENT_INSTALLATION_ID, "
        f'or put "installation_id" in {CONFIG_PATH}.'
    )


def repo():
    return os.environ.get("WISH_AGENT_REPO", DEFAULT_REPO)


def _read_private_key():
    path = key_path()
    if os.name != "nt":
        # Mirrors what `ssh` does with a private key, and for the same
        # reason: a key another local account can read is not private.
        try:
            mode = os.stat(path).st_mode
        except FileNotFoundError:
            raise ConfigError(
                f"No private key at {path}. Set $WISH_AGENT_KEY, or put the "
                "App's key there."
            ) from None
        if mode & 0o077:
            raise ConfigError(
                f"{path} is readable by group or other (mode "
                f"{oct(stat.S_IMODE(mode))}). Run: chmod 600 {path}"
            )
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise ConfigError(
            f"No private key at {path}. Set $WISH_AGENT_KEY, or put the "
            "App's key there."
        ) from None


# ---------------------------------------------------------------------------
# Authentication


def make_jwt():
    """A short-lived App-level JWT, good for `GET /app` and minting a token."""
    key = _read_private_key()
    now = int(time.time())
    payload = {
        "iat": now - IAT_SKEW_SECONDS,
        "exp": now + EXP_AHEAD_SECONDS,
        "iss": app_id(),
    }
    return jwt.encode(payload, key, algorithm="RS256")


def get_installation_token():
    """An installation token scoped to `issues: write` on this repository.

    Cached in this process only, and re-minted once it is within a minute of
    the expiry GitHub gave it.
    """
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] - 60 > now:
        return _token_cache["token"]

    jwt_token = make_jwt()
    iid = installation_id()
    # A token can only ever be narrower than the installation it comes from,
    # so asking for less than was granted costs nothing and limits what a
    # leaked token can do.
    body = {
        "repositories": [repo().rsplit("/", 1)[-1]],
        "permissions": {"issues": "write"},
    }
    status, _headers, raw = _call(
        "POST", f"/app/installations/{iid}/access_tokens", jwt_token, body=body
    )
    if status == 401:
        raise ApiError(
            "401 minting an installation token. Check $WISH_AGENT_APP_ID / "
            "config.json's app_id, and check this machine's clock is not "
            "skewed.",
            status,
        )
    if status == 404:
        raise ApiError(
            "404 minting an installation token. Either the App is not "
            "installed on this repository, or the installation ID is wrong.",
            status,
        )
    if status >= 400:
        raise ApiError(
            f"{status} minting an installation token: {_error_detail(raw)}",
            status,
        )

    data = json.loads(raw)
    _token_cache["token"] = data["token"]
    _token_cache["expires_at"] = _parse_github_time(data["expires_at"])
    return _token_cache["token"]


def _parse_github_time(value):
    return (
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _error_detail(raw):
    try:
        return json.loads(raw).get("message", "")
    except (ValueError, AttributeError):
        pass
    return raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)


# ---------------------------------------------------------------------------
# HTTP


def _request(method, url, headers, body):
    """The one function that reaches the network. Tests replace this."""
    data = None
    sent_headers = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        sent_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=sent_headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def _call(method, path_or_url, token, body=None):
    """One authenticated round trip, retrying a 5xx and never a 4xx.

    Retrying a 403 in a loop is how a rate limit gets burnt; a 5xx is
    transient enough to deserve two tries with a short backoff.
    """
    url = path_or_url if path_or_url.startswith("http") else API + path_or_url
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "wish-agent-tool",
    }
    attempt = 0
    while True:
        status, resp_headers, raw = _request(method, url, headers, body)
        if status >= 500 and attempt < MAX_5XX_RETRIES:
            attempt += 1
            time.sleep(0.5 * attempt)
            continue
        return status, resp_headers, raw


def _api_call(method, path, body=None):
    """An authenticated call using the (cached) installation token."""
    token = get_installation_token()
    return _call(method, path, token, body=body)


# ---------------------------------------------------------------------------
# Operations


def whoami():
    token = make_jwt()
    status, _headers, raw = _call("GET", "/app", token)
    if status >= 400:
        raise ApiError(f"{status} from GET /app: {_error_detail(raw)}", status)
    return json.loads(raw)["slug"] + "[bot]"


def _issues_path(number=None, suffix=""):
    tail = f"/{number}" if number is not None else ""
    return f"/repos/{repo()}/issues{tail}{suffix}"


def create_issue(title, body_text, labels=()):
    payload = {"title": title, "body": body_text}
    if labels:
        payload["labels"] = list(labels)
    status, _headers, raw = _api_call("POST", _issues_path(), body=payload)
    if status >= 400:
        raise ApiError(f"{status} creating an issue: {_error_detail(raw)}", status)
    return json.loads(raw)["number"]


def comment_on_issue(number, body_text):
    status, _headers, raw = _api_call(
        "POST", _issues_path(number, "/comments"), body={"body": body_text}
    )
    if status == 403:
        raise ApiError(
            f"403 commenting on #{number}. The issue may be locked, and the "
            "installation may lack the access a locked issue needs -- see "
            "docs/218-the-wish-agent-bot.md.",
            status,
        )
    if status >= 400:
        raise ApiError(
            f"{status} commenting on #{number}: {_error_detail(raw)}", status
        )
    return json.loads(raw)["html_url"]


def close_issue(number, comment_text=None):
    if comment_text:
        comment_on_issue(number, comment_text)
    status, _headers, raw = _api_call(
        "PATCH", _issues_path(number), body={"state": "closed"}
    )
    if status >= 400:
        raise ApiError(f"{status} closing #{number}: {_error_detail(raw)}", status)


def label_issue(number, add=(), remove=()):
    if add:
        status, _headers, raw = _api_call(
            "POST", _issues_path(number, "/labels"), body={"labels": list(add)}
        )
        if status >= 400:
            raise ApiError(
                f"{status} adding labels to #{number}: {_error_detail(raw)}",
                status,
            )
    for name in remove:
        encoded = urllib.parse.quote(name, safe="")
        status, _headers, raw = _api_call(
            "DELETE", _issues_path(number, f"/labels/{encoded}")
        )
        if status >= 400:
            raise ApiError(
                f"{status} removing label {name!r} from #{number}: "
                f"{_error_detail(raw)}",
                status,
            )


def edit_comment(comment_id, body_text):
    status, _headers, raw = _api_call(
        "PATCH", f"/repos/{repo()}/issues/comments/{comment_id}", body={"body": body_text}
    )
    if status >= 400:
        raise ApiError(
            f"{status} editing comment {comment_id}: {_error_detail(raw)}", status
        )
    return json.loads(raw)["html_url"]


# ---------------------------------------------------------------------------
# CLI


def _read_body_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_parser():
    parser = argparse.ArgumentParser(prog="wishagent.py")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("whoami")
    sub.add_parser("token")

    p_create = sub.add_parser("create")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--body-file", required=True)
    p_create.add_argument("--label", action="append", default=[], dest="labels")

    p_comment = sub.add_parser("comment")
    p_comment.add_argument("number", type=int)
    p_comment.add_argument("--body-file", required=True)

    p_close = sub.add_parser("close")
    p_close.add_argument("number", type=int)
    p_close.add_argument("--comment-file")

    p_label = sub.add_parser("label")
    p_label.add_argument("number", type=int)
    p_label.add_argument("--add", action="append", default=[], dest="add")
    p_label.add_argument("--remove", action="append", default=[], dest="remove")

    p_edit = sub.add_parser("edit-comment")
    p_edit.add_argument("id", type=int)
    p_edit.add_argument("--body-file", required=True)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "whoami":
            print(whoami())
        elif args.command == "token":
            print(get_installation_token())
        elif args.command == "create":
            body_text = _read_body_file(args.body_file)
            print(create_issue(args.title, body_text, args.labels))
        elif args.command == "comment":
            body_text = _read_body_file(args.body_file)
            print(comment_on_issue(args.number, body_text))
        elif args.command == "close":
            comment_text = (
                _read_body_file(args.comment_file) if args.comment_file else None
            )
            close_issue(args.number, comment_text)
            print(f"closed #{args.number}")
        elif args.command == "label":
            label_issue(args.number, args.add, args.remove)
            print(f"labelled #{args.number}")
        elif args.command == "edit-comment":
            body_text = _read_body_file(args.body_file)
            print(edit_comment(args.id, body_text))
    except (ConfigError, ApiError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
