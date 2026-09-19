#!/usr/bin/env python3
"""Speak to GitHub as the `wish-agent` App, not as Donald's own account.

    tools/wishagent.py whoami
    tools/wishagent.py token
    tools/wishagent.py push-token
    tools/wishagent.py git-credential [get|store|erase]
    tools/wishagent.py create  --title T --body-file F [--label L]...
    tools/wishagent.py comment N --body-file F
    tools/wishagent.py close   N [--comment-file F]
    tools/wishagent.py reopen  N [--comment-file F]
    tools/wishagent.py label   N [--add L]... [--remove L]...
    tools/wishagent.py edit    N [--title T] [--body-file F] [--comment-file F]
    tools/wishagent.py edit-comment ID --body-file F

An issue or comment filed by an agent should say so in its byline, and a
GitHub App is how that happens without handing an agent Donald's own
credentials: `wish-agent[bot]` is the author instead of him. This mints the
App's short-lived JWT, exchanges it for an installation token scoped to
`issues: write` on this one repository, and makes the REST call -- never
GraphQL, and never `gh issue`'s own sub-commands, which resolve labels
through GraphQL where an installation token is accepted unevenly.

Two modes, and a token is only ever as wide as the mode that minted it:

* **issues** -- `token`, and every issue command above. `issues: write` only.
* **push** -- `push-token` and `git-credential`. `contents: write` and
  `workflows: write`, for a machine that pushes as the App instead of holding
  anybody's SSH key or `gh` login. `git-credential` is a git credential helper:

      git config credential.https://github.com.helper \
          '!/path/to/python /path/to/tools/wishagent.py git-credential'

  git asks it for host `github.com` and it answers with username
  `x-access-token` and a token minted for that one request, so a push over
  HTTPS needs no token stored anywhere *by this tool*. A push-mode token is
  minted on every call and cached nowhere -- not in the process, not on disk --
  because a credential helper is a fresh process for each request anyway, and
  because the token can rewrite the repository. git offers what it was given to
  every helper it has configured, so a machine that also has a helper which
  stores credentials (`store`, `manager`, `osxkeychain`) should reset the list
  first: `git config --global --add credential.https://github.com.helper ''`,
  then the line above.

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
REQUEST_TIMEOUT = 30

# What each mode asks the installation for. A token can only be narrower than
# the installation it comes from, so asking for exactly this costs nothing and
# limits what a leaked token can do.
ISSUES_PERMISSIONS = {"issues": "write"}
PUSH_PERMISSIONS = {"contents": "write", "workflows": "write"}

# The user name a GitHub App installation token is presented under over HTTPS.
GIT_USERNAME = "x-access-token"

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
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f"Could not read {CONFIG_PATH}: {e}") from e


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
    value = os.environ.get("WISH_AGENT_REPO")
    return value if value else DEFAULT_REPO


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


def _mint_installation_token(permissions):
    """Ask GitHub for an installation token with exactly `permissions`.

    Returns `(token, expires_at)`. Both modes come through here, so a bad
    App ID, a skewed clock and an uninstalled App read the same way in each.
    """
    jwt_token = make_jwt()
    iid = installation_id()
    body = {
        "repositories": [repo().rsplit("/", 1)[-1]],
        "permissions": dict(permissions),
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
    return data["token"], _parse_github_time(data["expires_at"])


def get_installation_token():
    """An installation token scoped to `issues: write` on this repository.

    Cached in this process only, and re-minted once it is within a minute of
    the expiry GitHub gave it.
    """
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] - 60 > now:
        return _token_cache["token"]

    token, expires_at = _mint_installation_token(ISSUES_PERMISSIONS)
    _token_cache["token"] = token
    _token_cache["expires_at"] = expires_at
    return token


def get_push_token():
    """A token that can push: `contents: write` and `workflows: write`.

    Minted on every call and cached nowhere. `_token_cache` is the issues
    token's and stays that way: a push token found there would be handed to
    anything that asks for an issues token, and the reverse would not push.
    """
    token, _expires_at = _mint_installation_token(PUSH_PERMISSIONS)
    return token


def answer_git_credential(action, request_text):
    """What a git credential helper prints for `action`, given git's request.

    git sends `key=value` lines ending in a blank line. Only `get` for
    `github.com` over HTTPS is answered; `store` and `erase` are ignored, since
    nothing is kept to store or erase, and any other host, or a request that
    does not say `https`, gets no answer at all.

    The request is split on `\n` and nothing else. `str.splitlines()` also
    splits on `\v`, `\f`, `\x1c`-`\x1e`, `\x85` and U+2028/9, which git
    passes through inside a value, and a later `host=` would then overwrite the
    real one: a user name of `a<VT>host=github.com` on a URL for another host
    would be answered with a push token. A stray `\r` is left in the value, so
    it fails the comparison and gets no answer either.
    """
    if action != "get":
        return ""
    request = {}
    for line in request_text.split("\n"):
        if line == "":
            break
        key, _, value = line.partition("=")
        request[key] = value
    if request.get("host") != "github.com":
        return ""
    if request.get("protocol") != "https":
        return ""
    return f"username={GIT_USERNAME}\npassword={get_push_token()}\n"


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
    """The one function that reaches the network. Tests replace this.

    An `HTTPError` still carries a status GitHub sent, so it is returned like
    any other response and left to `_call`'s 5xx retry. A `URLError` or a
    bare `OSError` -- DNS failure, connection refused, reset, a hung TLS
    handshake -- carries no status at all, so there is nothing for that retry
    loop to inspect; it is raised as `ApiError` here and left uncaught, which
    fails the call immediately rather than looping on a problem `_call`'s
    retry was never written to reason about.
    """
    data = None
    sent_headers = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        sent_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=sent_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except (urllib.error.URLError, OSError) as e:
        raise ApiError(f"{method} {url} failed: {e}") from e


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


def reopen_issue(number, comment_text=None):
    """Set an issue's state back to open.

    `comment_text`, when given, is posted after the state change succeeds: a
    comment explaining a reopen must not appear on an issue that is still
    closed.
    """
    status, _headers, raw = _api_call(
        "PATCH", _issues_path(number), body={"state": "open"}
    )
    if status >= 400:
        raise ApiError(f"{status} reopening #{number}: {_error_detail(raw)}", status)
    if comment_text:
        comment_on_issue(number, comment_text)


def edit_issue(number, title=None, body_text=None, comment_text=None):
    """Correct an issue's own title and/or body -- `.claude/rules/issues.md`:
    "Edit the description only to correct a factual error in it, and say in a
    comment that you did."

    Only the fields actually given go into the `PATCH` payload, so a
    title-only correction leaves the body untouched and vice versa -- sending
    both always would silently overwrite whichever one the caller did not
    mean to touch.

    `comment_text`, when given, is posted *after* the `PATCH` succeeds, the
    opposite order from `close_issue`. A comment claiming a correction that
    then failed would be a lie on a public tracker; a close whose comment
    posts but whose state-change then fails just leaves a truthful comment on
    an issue that is still open.
    """
    payload = {}
    if title is not None:
        payload["title"] = title
    if body_text is not None:
        payload["body"] = body_text
    status, _headers, raw = _api_call("PATCH", _issues_path(number), body=payload)
    if status >= 400:
        raise ApiError(f"{status} editing #{number}: {_error_detail(raw)}", status)
    result = json.loads(raw)["html_url"]
    if comment_text:
        comment_on_issue(number, comment_text)
    return result


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
    sub.add_parser("push-token")

    p_credential = sub.add_parser("git-credential")
    # Any action, not just get/store/erase: git's credential protocol asks a
    # helper to ignore one it does not know, and answer_git_credential does.
    p_credential.add_argument("action", nargs="?", default="get")

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

    p_reopen = sub.add_parser("reopen")
    p_reopen.add_argument("number", type=int)
    p_reopen.add_argument("--comment-file")

    p_label = sub.add_parser("label")
    p_label.add_argument("number", type=int)
    p_label.add_argument("--add", action="append", default=[], dest="add")
    p_label.add_argument("--remove", action="append", default=[], dest="remove")

    p_edit_issue = sub.add_parser("edit")
    p_edit_issue.add_argument("number", type=int)
    p_edit_issue.add_argument("--title")
    p_edit_issue.add_argument("--body-file")
    p_edit_issue.add_argument("--comment-file")

    p_edit = sub.add_parser("edit-comment")
    p_edit.add_argument("id", type=int)
    p_edit.add_argument("--body-file", required=True)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "whoami":
            print(whoami())
        elif args.command == "token":
            print(get_installation_token())
        elif args.command == "push-token":
            print(get_push_token())
        elif args.command == "git-credential":
            # No print(): git wants exactly the answer and no trailing blank.
            sys.stdout.write(answer_git_credential(args.action, sys.stdin.read()))
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
        elif args.command == "reopen":
            comment_text = (
                _read_body_file(args.comment_file) if args.comment_file else None
            )
            reopen_issue(args.number, comment_text)
            print(f"reopened #{args.number}")
        elif args.command == "label":
            label_issue(args.number, args.add, args.remove)
            print(f"labelled #{args.number}")
        elif args.command == "edit":
            if args.title is None and args.body_file is None:
                parser.error("edit needs --title, --body-file, or both")
            body_text = (
                _read_body_file(args.body_file) if args.body_file else None
            )
            comment_text = (
                _read_body_file(args.comment_file) if args.comment_file else None
            )
            print(edit_issue(
                args.number, title=args.title, body_text=body_text,
                comment_text=comment_text,
            ))
        elif args.command == "edit-comment":
            body_text = _read_body_file(args.body_file)
            print(edit_comment(args.id, body_text))
    except (ConfigError, ApiError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
