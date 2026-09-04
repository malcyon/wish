#!/usr/bin/env python3
"""Refuse a reply that cites an issue number without saying what it is.

A bare `#59` makes Donald do the lookup: fast for the assistant, which has
the number in hand, and slow for him, who has to go and find out what it is
before the sentence means anything -- *"when you only reference a number, it
never means anything to me."* This docstring used to say the reason was that
he reads replies with no browser open. It is not, and he corrected it on
2026-09-02: *"It should not matter if I have a web browser open or not.
You're forcing me to manually look up every number. That is fast for you, but
slow for me."* The rule is the first one in `CLAUDE.md`, and it went on
being broken anyway -- so this was written to stop it being a matter of
remembering.

**It is not registered today.** `3ee1a3f "Disable github issue hooks."`
(2026-09-03) took this and its sibling out of `.claude/settings.json`. The
script still works and still runs by hand; it simply is not wired to `Stop`,
so the rule is a matter of remembering again.

A `Stop` hook: it reads the transcript, looks at the last thing the assistant
said, and exits 2 with a reason if any `#N` in it is not followed by a title
in parentheses. Exit 2 feeds stderr back rather than showing it to Donald, so
the reply is rewritten before he ever sees it.

Deliberately not flagged, because each is a place the number is already
readable or is not an issue reference at all:
  * a commit message -- `.claude/rules/commits.md` rules the number goes bare
    in parentheses at the end of the one line, and GitHub hotlinks it there;
  * anything inside a **fenced** code block, which is quoted output rather
    than prose;
  * a `#` that is a heading, a colour, a Python comment or an issue URL.

**A single-backtick span is prose and is checked.** It did not used to be,
and that hole swallowed the rule for the commonest case: citations in this
project are written as `` `#59 (Map the DOS saved game...)` ``, so blanking
backticks meant every citation -- named or bare -- was invisible to this
hook, and a bare `` `#53` `` sailed through. Found on 2026-09-02 after six
issue comments went out with bare numbers in backticks. A `#` followed by
digits inside backticks is overwhelmingly an issue reference here; if a real
false positive ever turns up, fix it by narrowing the pattern rather than by
restoring the blanket exemption.
"""
import json
import re
import sys

# `#123` in prose. Not `##123`, not `#12ab`, not part of a URL or a colour.
CITATION = re.compile(r"(?<![\w#/&])#(\d{1,6})\b")

# What counts as naming it: an opening parenthesis straight after, which is
# `#59 (Map the DOS saved game...)`. A bare number is what we refuse.
NAMED = re.compile(r"\s*\(")

# The commit-message form, where `CLAUDE.md` rules the number goes bare: it
# is inside parentheses at the end of the one line, and GitHub hotlinks it
# there. `(closes #14)`, `(fixes #14)`, `(#10)` -- a title would break the
# sentence, so quoting a commit message must not be refused here.
COMMIT_FORM = re.compile(r"\((?:closes\s+|close\s+|fixes\s+|fix\s+)?$", re.I)

# Fenced blocks only. Single-backtick spans are prose here -- see the module
# docstring for why blanking them defeated the rule.
FENCE = re.compile(r"```.*?```", re.S)


def prose_only(text: str) -> str:
    """The text with code spans and fenced blocks blanked out.

    Blanked rather than removed so the offsets still line up with what a
    reader sees. Headings are left alone deliberately: a heading is prose
    somebody reads, so a number in one needs its title like any other.
    """
    return FENCE.sub(lambda m: " " * len(m.group(0)), text)


def last_assistant_text(path: str) -> str:
    """Everything the assistant said in its final turn, as one string."""
    said: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "assistant":
                # A user turn ends the assistant's last run of messages.
                if event.get("type") == "user":
                    said.clear()
                continue
            content = event.get("message", {}).get("content", [])
            if isinstance(content, str):
                said.append(content)
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    said.append(part.get("text", ""))
    return "\n".join(said)


def bare_numbers(text: str) -> list[str]:
    found: list[str] = []
    clean = prose_only(text)
    for m in CITATION.finditer(clean):
        if NAMED.match(clean, m.end()):
            continue                    # `#59 (Map the DOS saved game...)`
        if COMMIT_FORM.search(clean[:m.start()]):
            continue                    # `(closes #14)` in a commit message
        found.append(m.group(0))
    return sorted(set(found), key=lambda s: int(s[1:]))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                        # never block on a malformed payload

    if payload.get("stop_hook_active"):
        return 0                        # already rewriting; do not loop

    path = payload.get("transcript_path")
    if not path:
        return 0
    try:
        text = last_assistant_text(path)
    except OSError:
        return 0

    bare = bare_numbers(text)
    if not bare:
        return 0

    print(
        "Rewrite the reply before sending it: "
        + ", ".join(bare)
        + " each cite an issue without saying what it is.\n\n"
        "A bare number makes Donald look it up: fast for you, slow for him. "
        "Name every one, at every mention -- there is no "
        '"already introduced it above" exemption, and this includes tables '
        "and the prose around them.\n\n"
        "    #59 (Map the DOS saved game, not just the character record)\n\n"
        "Get each title with:\n"
        "    gh issue view N --json number,title -q '\"#\\(.number) "
        '(\\(.title))"\'\n\n'
        "(`gh issue view N` on its own fails on this repo with a "
        "Projects-classic GraphQL error, so pass --json.)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
