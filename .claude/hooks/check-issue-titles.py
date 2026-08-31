#!/usr/bin/env python3
"""Refuse a reply that cites an issue number without saying what it is.

Donald reads these replies without a browser open, and a bare `#59` carries
nothing at all to him: *"when you only reference a number, it never means
anything to me."* The rule has been in `CLAUDE.md` since the Issues section
was written, it is restated in the Replies section three hundred lines later,
and it went on being broken -- so this stops being a matter of remembering it.

A `Stop` hook: it reads the transcript, looks at the last thing the assistant
said, and exits 2 with a reason if any `#N` in it is not followed by a title
in parentheses. Exit 2 feeds stderr back rather than showing it to Donald, so
the reply is rewritten before he ever sees it.

Deliberately not flagged, because each is a place the number is already
readable or is not an issue reference at all:
  * a commit message -- `CLAUDE.md` rules the number goes bare in parentheses
    at the end of the one line, and GitHub hotlinks it there;
  * anything inside a fenced code block or backticks, which is quoted output
    rather than prose;
  * a `#` that is a heading, a colour, a Python comment or an issue URL.
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

FENCE = re.compile(r"```.*?```|`[^`\n]*`", re.S)


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
        "Donald reads these without a browser open, so a bare number carries "
        "nothing to him. Name every one, at every mention -- there is no "
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
