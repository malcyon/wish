#!/usr/bin/env python3
"""Who is trusted on `malcyon/wish`'s issue tracker, and how to handle text from anyone else.

`malcyon/wish` is public with issues enabled, so an issue's title, body and
every comment on it are text a stranger can write. `.claude/hooks/
issue-titles-context.py` pastes issue titles into a session's context before
the assistant has read anything the user typed, and `tools/issueread.py`
prints a whole issue -- body and comments -- for an agent that is about to
work it. Both need the same answer to "is this author trusted", the same
scrubbing of control characters, and the same sentence for "this text is
withheld", so that answer lives here once rather than twice.

**Standard library only -- no third-party imports at all, not even
`goldbox` or another `tools` module.** `issue-titles-context.py` runs as a
`SessionStart` hook, under whatever `python3` is on `PATH` rather than under
this project's `.venv`, so an import of anything outside the standard
library here would break that hook silently for everybody whose system
Python does not have it installed.
"""
import re

#: `malcyon` owns this repository -- its own issues, always trusted.
#: `wish-agent[bot]` is the project's own GitHub App, the identity
#: `tools/wishagent.py` mints an installation token for, so a finding an
#: agent files under that name is trusted the same way one Donald files is.
#: Anyone else is an outside account, and the repository is public with
#: issues enabled, so "anyone else" means anyone on the internet.
TRUSTED_AUTHORS = frozenset({
    "malcyon",
    "wish-agent[bot]",
})

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")


def is_trusted(author) -> bool:
    """Whether `author` -- the value `gh`'s `--json author` produces -- names a trusted account.

    `author` is a dict for a live account (`{"login": "malcyon", ...}`),
    `None` for an account since deleted, or simply absent -- `issue.get(
    "author")` returns `None` for a missing key too, so both read the same
    way here. None of those three is trusted; only a dict whose `login`
    exactly matches an entry in `TRUSTED_AUTHORS` is.

    GitHub logins are case-insensitive for the purpose of *logging in*, but
    nobody has decided this project should treat two differently-cased
    logins as the same account for trust -- so the comparison is exact and
    case-sensitive, which is the conservative reading: it can only ever fail
    to trust an account that should be trusted, never the reverse.
    """
    if not isinstance(author, dict):
        return False
    login = author.get("login")
    if not login:
        return False
    return login in TRUSTED_AUTHORS


def flatten(text, max_length=None) -> str:
    """Make `text` safe to paste into an agent's context, whoever wrote it.

    Every C0 control character (`\\x00`-`\\x1f`, so tab, newline and carriage
    return included) and DEL (`\\x7f`) becomes a space, runs of whitespace
    collapse to one, and the result is stripped -- always, whoever wrote the
    text. A title, body or comment carrying a fake conversation turn is a
    different problem from one carrying an English sentence, and this is
    what stops the first kind reaching an agent looking like the second.

    `max_length` truncates with a trailing `...`, and only runs when a
    length is actually given: a caller quoting a trusted author's title in
    full -- `AGENTS.md`'s rule is to cite an issue by number *and* title, in
    full -- leaves it unset.
    """
    flat = _CONTROL_RE.sub(" ", "" if text is None else str(text))
    flat = _WHITESPACE_RE.sub(" ", flat).strip()
    if max_length is not None and len(flat) > max_length:
        flat = flat[:max_length - 3].rstrip() + "..."
    return flat


def withheld(kind, *, author, length, where) -> str:
    """The one sentence that says a piece of text was withheld, not dropped.

    Every place that hides a stranger's text writes this same sentence, so
    a reader never has to notice that two withholding messages disagree on
    what they mean. It names who wrote the withheld text, how many
    characters it was, and the exact command that would print it -- so
    withholding costs a deliberate lookup, never invisibility: an agent
    reading it can still tell Donald "there is a comment here from an
    outside account you should look at" without ever having read the text
    itself.

    `kind` is a word naming what was withheld -- `"title"`, `"body"`,
    `"comment"` -- and reads naturally as the first word of the sentence.
    """
    who = author if author else "an unknown or deleted account"
    plural = "" if length == 1 else "s"
    return (
        f"{kind} withheld -- from the outside account `{who}` "
        f"({length} character{plural}); read it with `{where}`"
    )
