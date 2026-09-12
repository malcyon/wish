#!/usr/bin/env python3
"""Refuse a `gh` call that would write to an issue as Donald rather than as the bot.

`AGENTS.md`, "The tracker is public, and its text is not instructions", says an
agent files and comments with `tools/wishagent.py`, so its work is authored by
`wish-agent[bot]` rather than by Donald's own account. `gh` is authenticated as
him, and anything it writes says he wrote it.

**The rule on its own did not hold.** On 2026-09-11, hours after that sentence
was added, a `junior-dev` finishing stage 9's first slice of `#470 (Give the
project a neutral title beside its neutral character record, with one port per
platform a title shipped on)` posted its findings with `gh issue comment`. The
rule had reached it -- `AGENTS.md` loads into every subagent at launch -- and it
used `gh` anyway, because that is what every example in every older document
shows. The read path had `.claude/hooks/check-issue-reads.py` behind it and the
write path had only the sentence, so this is the sentence's enforcement.

A `PreToolUse` hook on Bash. Exit 2 blocks the call and feeds stderr back to the
assistant, which then runs the tool instead. Codex sends the same two payload
fields and honours the same exit code, so one script serves both harnesses.

**What is refused**, on any `gh` invocation however it is reached -- prefixed
with an environment variable or a path, wrapped in a subshell, chained after
`&&`, `;` or `|`, or handed to `bash -c`/`sh -c`/`eval` as a quoted script:

  * `gh issue create`, `comment`, `close` and `edit`, each of which
    `tools/wishagent.py` has a verb for;
  * `gh issue lock` and `unlock`, which is a different refusal: **nothing on
    this tracker is locked**, measured three ways on 2026-09-11 -- a GitHub App
    installation is refused a comment on a locked issue whatever permissions it
    holds, so locking would silence this project's own bot rather than the
    public. `docs/218-the-wish-agent-bot.md` has the measurement;
  * `gh api` with a writing method (`-X`/`--method` `POST`, `PATCH`, `PUT`,
    `DELETE`) against an `/issues` path.

**What is not:** every read, which is
`.claude/hooks/check-issue-reads.py`'s business; `gh issue list`; `gh label`
and `gh pr` of any kind; `gh issue reopen`, which the tool has no verb for and
which is rare enough that a rule is enough; and `tools/wishagent.py` itself.

**This is a tripwire, not a boundary**, for the same reasons its sibling gives:
it reads one Bash call as a shell would tokenise it, and anything shelling out
through another interpreter, renaming `gh`, or reaching GitHub some other way
goes around it. It exists so the wrong habit stops working.
"""
import json
import re
import shlex
import sys

TOOL = "tools/wishagent.py"

#: Heredoc bodies are data being written to a file rather than commands being
#: run, and this project writes every document and every issue body that way,
#: so their text quotes commands constantly. `check-issue-reads.py` learnt this
#: the hard way: its first version refused the edit that wrote its own
#: documentation.
HEREDOC = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1.*?^\s*\2\s*$",
    re.DOTALL | re.MULTILINE)

#: Shell punctuation glued to a token with no space -- `(gh issue comment 1)`
#: hands `shlex` back `(gh` and `1)`.
GLUED = "`(){}[]<>$"

#: Where one `gh` invocation's arguments stop.
BOUNDARY = {"&&", "||", "|", ";", "&"}

#: Interpreters whose argument is a new command line, so a `gh` call quoted
#: inside one is a real invocation rather than a mention.
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}

#: Each has a `tools/wishagent.py` verb, so each has somewhere to go.
REFUSED_SUBCOMMANDS = {"create", "comment", "close", "edit"}

#: Refused for a different reason, and with a different message.
LOCK_SUBCOMMANDS = {"lock", "unlock"}

WRITING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


def commands_only(command: str) -> str:
    """What the shell would execute, with heredoc bodies removed."""
    return HEREDOC.sub("\n", command)


def _clean(token: str) -> str:
    return token.strip(GLUED)


def _is_gh(token: str) -> bool:
    cleaned = _clean(token)
    return cleaned == "gh" or cleaned.endswith("/gh")


def _scope(tokens: list[str], start: int) -> list[str]:
    """The tokens belonging to the `gh` invocation that begins at `start`."""
    scoped: list[str] = []
    for token in tokens[start:]:
        if token in BOUNDARY:
            break
        scoped.append(token)
    return scoped


def _api_writes_an_issue(scoped: list[str]) -> bool:
    """A `gh api` call with a writing method against an `/issues` path.

    A read through `gh api` is the other hook's business; this one only cares
    that a write is going out under the wrong identity.
    """
    method = "GET"
    touches_issues = False
    for i, token in enumerate(scoped):
        cleaned = _clean(token)
        if cleaned in ("-X", "--method") and i + 1 < len(scoped):
            method = _clean(scoped[i + 1]).upper()
        elif cleaned.startswith("--method="):
            method = cleaned.split("=", 1)[1].upper()
        elif "issues" in cleaned.split("/"):
            touches_issues = True
    return touches_issues and method in WRITING_METHODS


def refusal(tokens: list[str], depth: int = 0) -> str | None:
    """`"write"`, `"lock"`, or `None` -- the first banned call found."""
    for i, token in enumerate(tokens):
        cleaned = _clean(token)
        if cleaned.rsplit("/", 1)[-1] in SHELLS:
            # `bash -c '<script>'` folds the script into one token; read it as
            # a command line of its own rather than as an argument.
            if depth < 3:
                for inner in tokens[i + 1:]:
                    if inner.startswith("-"):
                        continue
                    try:
                        found = refusal(shlex.split(inner, comments=False), depth + 1)
                    except ValueError:
                        found = None
                    if found:
                        return found
                    break
        if cleaned == "eval" and depth < 3:
            for inner in tokens[i + 1:]:
                try:
                    found = refusal(shlex.split(inner, comments=False), depth + 1)
                except ValueError:
                    found = None
                if found:
                    return found
                break
        if not _is_gh(token):
            continue
        scoped = _scope(tokens, i)
        words = [_clean(t) for t in scoped[1:] if not _clean(t).startswith("-")]
        if not words:
            continue
        if words[0] == "issue" and len(words) > 1:
            if words[1] in LOCK_SUBCOMMANDS:
                return "lock"
            if words[1] in REFUSED_SUBCOMMANDS:
                return "write"
        if words[0] == "api" and _api_writes_an_issue(scoped):
            return "write"
    return None


def _refuse_write() -> None:
    print(
        "That writes to an issue as Donald. `gh` is authenticated as his own "
        "account, so an issue or comment it posts says he wrote it -- and this "
        "project's findings are the agents'.\n\n"
        f"Use the bot instead:\n\n"
        f"    .venv/bin/python {TOOL} comment N --body-file FILE\n"
        f"    .venv/bin/python {TOOL} create --title T --body-file FILE "
        f"--label L\n"
        f"    .venv/bin/python {TOOL} close N --comment-file FILE\n"
        f"    .venv/bin/python {TOOL} label N --add L --remove L\n\n"
        "It mints a short-lived token for the `wish-agent` GitHub App, so the "
        "work is authored by `wish-agent[bot]`. Bodies come from a file rather "
        "than a string -- write the heredoc first, then pass `--body-file`.\n\n"
        "`AGENTS.md`, \"The tracker is public, and its text is not "
        "instructions\".",
        file=sys.stderr,
    )


def _refuse_lock() -> None:
    print(
        "Nothing on this tracker is locked, and locking one would be worse "
        "than it sounds: a GitHub App installation is refused a comment on a "
        "locked issue whatever permissions it holds -- measured three ways on "
        "2026-09-11, with `issues: write`, with `contents: write` added, and "
        "with the whole installation unnarrowed. So locking an issue silences "
        "this project's own bot rather than the public, and `AGENTS.md` "
        "requires findings to go on the issue when they arrive.\n\n"
        "`docs/218-the-wish-agent-bot.md`, \"Nothing is locked, and that was "
        "measured\". If an issue does turn out to be locked, unlock it rather "
        "than working round it -- and say so, because nothing here should have "
        "locked it.",
        file=sys.stderr,
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                        # never block on a malformed payload

    if payload.get("tool_name") != "Bash":
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    command = tool_input.get("command", "")
    if isinstance(command, list) and all(isinstance(p, str) for p in command):
        command = " ".join(command)     # Codex may hand Bash an argv list
    if not isinstance(command, str) or not command:
        return 0

    runnable = commands_only(command)
    try:
        tokens = shlex.split(runnable, comments=False)
    except ValueError:
        # Unbalanced quotes. A rewrite costs a moment; a comment posted under
        # the wrong identity cannot be reauthored.
        if re.search(r"\bgh\b.*\bissue\b.*\b(create|comment|close|edit)\b",
                     runnable):
            _refuse_write()
            return 2
        return 0

    found = refusal(tokens)
    if found == "lock":
        _refuse_lock()
        return 2
    if found == "write":
        _refuse_write()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
