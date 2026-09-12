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
#: `wish-agent` is the project's own GitHub App, the identity
#: `tools/wishagent.py` mints an installation token for, so a finding an
#: agent files under that name is trusted the same way one Donald files is.
#: Anyone else is an outside account, and the repository is public with
#: issues enabled, so "anyone else" means anyone on the internet.
#:
#: These are the *canonical* names. `gh` does not print either one this
#: plainly for a bot -- measured live against `malcyon/wish` on 2026-09-11,
#: with a real issue opened and commented on by the `wish-agent` App
#: installation:
#:
#: | route                                              | what it reports                              |
#: |-----------------------------------------------------|-----------------------------------------------|
#: | REST `POST /issues` response, `user.login`           | `wish-agent[bot]`                             |
#: | `gh issue view N --json author`                      | `{"is_bot": true, "login": "app/wish-agent"}` |
#: | `gh issue view N --json comments`, each comment's author | `{"login": "wish-agent"}` -- bare        |
#:
#: `is_trusted` strips those two wrappers before comparing, rather than
#: listing every spelling -- the first version of this file listed only
#: `wish-agent[bot]` and so trusted none of the three spellings `gh` actually
#: emits.
_OWNER = "malcyon"
_BOT = "wish-agent"
TRUSTED_AUTHORS = frozenset({_OWNER, _BOT})

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_BODY_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_bot_wrapper(login: str):
    """Peel gh's own `app/` prefix and `[bot]` suffix off `login`.

    Returns `(name, decorated)`: `name` is `login` with either wrapper
    removed, and `decorated` says whether either was present. A real GitHub
    username can contain neither `/` nor `[` -- GitHub restricts a chosen
    username to letters, digits and single hyphens -- so a login carrying
    one did not come from a person naming their own account; it came from
    `gh` rendering a bot or App actor. That is what makes stripping it safe
    *for the bot*: nothing but `gh`'s own rendering ever puts these
    characters in a login at all.

    It is not safe to read the other way round, which is why `is_trusted`
    below does not simply strip-then-compare against the whole of
    `TRUSTED_AUTHORS`. `malcyon` is a human account and gh never decorates a
    human login this way; a *different* GitHub App, one whose slug happened
    to be `malcyon`, would show up decorated too (`app/malcyon`,
    `malcyon[bot]`), and stripping it down to `malcyon` before checking
    membership would wrongly trust that unrelated App as though it were the
    repository's owner. So decoration is only ever taken as evidence of
    *the bot*, never of the owner.
    """
    decorated = False
    if login.startswith("app/"):
        login = login[len("app/"):]
        decorated = True
    if login.endswith("[bot]"):
        login = login[:-len("[bot]")]
        decorated = True
    return login, decorated


def is_trusted(author) -> bool:
    """Whether `author` -- the value `gh`'s `--json author` produces -- names a trusted account.

    `author` is a dict for a live account (`{"login": "malcyon", ...}`),
    `None` for an account since deleted, or simply absent -- `issue.get(
    "author")` returns `None` for a missing key too, so both read the same
    way here. None of those three is trusted.

    A bare login is trusted when it exactly matches an entry in
    `TRUSTED_AUTHORS`. A login `gh` has wrapped in `app/...` or `...[bot]`
    is trusted only when the name underneath is `wish-agent` specifically --
    see `_strip_bot_wrapper` for why the owner's name does not get the same
    treatment.

    `is_bot` in the dict is not consulted at all: any GitHub App commenting
    here carries `is_bot: true`, ours included, so it says nothing about
    *which* App this is. Trust turns on the name, never on that flag alone.

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
    name, decorated = _strip_bot_wrapper(login)
    if decorated:
        return name == _BOT
    return name in TRUSTED_AUTHORS


def flatten(text) -> str:
    """Make `text` -- a title -- safe to paste into an agent's context as one line.

    Every C0 control character (`\\x00`-`\\x1f`, so tab, newline and carriage
    return included) and DEL (`\\x7f`) becomes a space, runs of whitespace
    collapse to one, and the result is stripped -- always, whoever wrote the
    text. A title carrying a fake conversation turn is a different problem
    from one carrying an English sentence, and this is what stops the first
    kind reaching an agent looking like the second.

    **Titles only.** A title is one line by nature and is what gets pasted
    into a citation, so collapsing it costs nothing. A body or comment goes
    through `scrub_body` instead, which keeps its newlines: this project's
    issue bodies are Markdown with headings, bullet lists, tables and hex
    dumps, and running one through this function once destroyed all of it.
    """
    flat = _CONTROL_RE.sub(" ", "" if text is None else str(text))
    return _WHITESPACE_RE.sub(" ", flat).strip()


def scrub_body(text) -> str:
    """Make a trusted body or comment safe to paste into context, keeping its lines.

    Every C0 control character except `\\n` becomes a space -- `\\t`
    included, so a tab does not survive any more than any other control
    character does -- and so does DEL (`\\x7f`). Newlines survive, and
    nothing is collapsed or truncated: unlike a title, a body or comment
    here is Markdown with structure a reader needs, and `flatten`'s
    one-line treatment destroyed it.

    Only a *trusted* author's text is ever passed through this. An outside
    author's body or comment is withheld entirely by `withheld`, so nothing
    here has to defend against a fake conversation turn the way `flatten`
    does for a title.
    """
    return _BODY_CONTROL_RE.sub(" ", "" if text is None else str(text))


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
