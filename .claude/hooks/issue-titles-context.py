#!/usr/bin/env python3
"""Put the open issue list, with titles, into context at the start of a session.

`CLAUDE.md`'s first rule is that an issue is cited by number *and* title,
because a bare number makes Donald look it up -- fast for the assistant,
slow for him. The rule was stated twice
and broken five times in one session anyway, and the reason was not
disagreement: writing fast, the number is in hand and the title is not, and
looking each one up mid-sentence is friction that gets skipped.

`check-issue-titles.py` catches the mistake, but a `Stop` hook fires after the
reply has already been shown -- so Donald sees the wrong version, then the
right one. He asked whether he could see only the final version. He cannot,
from a `Stop` hook; the fix is to stop the mistake being made.

So this hands over the titles up front. About 1 000 tokens for 59 issues.

**Once per session, not once per message.** A `UserPromptSubmit` hook would
add a copy per turn -- forty turns is forty near-identical copies -- and the
list barely moves during a session. The only thing that changes it is the
assistant filing something, which the assistant already knows about.

Silent on any failure. `gh` may be unauthenticated, offline, or absent, and
none of that is a reason to interrupt somebody starting work.
"""
import json
import subprocess
import sys

TIMEOUT = 15
LIMIT = "300"


def main() -> int:
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass                            # the payload is not needed; carry on

    try:
        done = subprocess.run(
            ["gh", "issue", "list", "--limit", LIMIT, "--state", "open",
             "--json", "number,title,labels",
             "-q", r'.[] | "#\(.number) (\(.title))"'
                   r' + (if ([.labels[].name] | index("blocked"))'
                   r' then "  [blocked]" else "" end)'],
            capture_output=True, text=True, timeout=TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    if done.returncode != 0:
        return 0

    rows = [ln for ln in done.stdout.splitlines() if ln.strip()]
    if not rows:
        return 0

    print(
        f"The {len(rows)} open issues, so a citation never needs a lookup. "
        "CLAUDE.md's first rule: cite an issue by number AND title, at every "
        "mention, in replies, tables and the prose around them. Copy the "
        "form below exactly.\n\n"
        + "\n".join(rows)
        + "\n\nThis was read once, at the start of the session. An issue "
        "filed or closed since is not in it -- and one filed since was filed "
        "by this session, so its title is already known. Anything else, check "
        "with `gh issue view N --json number,title` (plain `gh issue view N` "
        "fails on this repo with a Projects-classic GraphQL error)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
