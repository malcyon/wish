#!/usr/bin/env python3
"""Refuse a `gh issue` body that cites an issue number without saying what it is.

The sibling `check-issue-titles.py` is a `Stop` hook: it reads what the
assistant said to Donald and refuses a bare `#59`. It never sees an issue
comment, because that leaves through Bash rather than through a reply -- and
`CLAUDE.md`'s Issues section says the rule covers "replies, issue comments and
documents", so half the rule had no guard at all.

Found on 2026-09-02, when Donald asked why the guard was not working: it was,
for replies, while six issue comments had gone out with bare numbers in them.

A `PreToolUse` hook on Bash. Exit 2 blocks the call and feeds stderr back, so
the body is rewritten before it is posted.

**What is checked.** The whole command text of any `gh issue create`,
`gh issue comment` or `gh issue edit`, plus the contents of any `--body-file`
that already exists. The command text is checked rather than only the parsed
`--body`, because the usual shape here writes a heredoc to a file and passes
`--body-file` in the same call -- at which point the file does not exist yet
and the body is only in the command string.

**The description of an issue is exempt, and that is Donald's ruling**, not an
oversight: *"Leave them alone. GitHub.com shows the ticket details on hover
and makes it a hotlink, so it will be fine."* An issue body is read on the
web. A **comment** is read in a terminal and in a notification mail, so it is
not exempt -- which is why `gh issue create` is checked only for the parts
that are not the body, and `gh issue comment` is checked whole.
"""
import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "_titles", os.path.join(HERE, "check-issue-titles.py"))
_titles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_titles)

GH_ISSUE = re.compile(r"\bgh\s+issue\s+(create|comment|edit)\b")

#: The other way a comment reaches GitHub from here: `gh api -X PATCH
#: /repos/.../issues/comments/<id>`, which is how an existing comment is
#: corrected. It does not say "gh issue", so the pattern above misses it.
GH_API_COMMENT = re.compile(r"\bgh\s+api\b[^\n]*issues/comments\b")

#: Sub-commands whose body is prose a person reads in a terminal. `create`
#: and `edit` write a *description*, which Donald has ruled is read on the web
#: and may carry bare numbers.
CHECKED = {"comment"}


def bodies(command: str) -> list[str]:
    """Every piece of prose this command would post.

    The command text itself, because a heredoc body lives there and the file
    it is written to does not exist yet at `PreToolUse` time; plus any
    `--body-file` that does already exist.
    """
    out = [command]
    try:
        tokens = shlex.split(command, comments=False)
    except ValueError:
        return out                      # unbalanced quotes; the text will do
    for i, tok in enumerate(tokens):
        if tok == "--body-file" and i + 1 < len(tokens):
            path = tokens[i + 1]
            try:
                with open(path, encoding="utf-8") as fh:
                    out.append(fh.read())
            except OSError:
                pass                    # not written yet -- it is in the text
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                        # never block on a malformed payload

    if payload.get("tool_name") != "Bash":
        return 0
    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        return 0

    subs = {m.group(1) for m in GH_ISSUE.finditer(command)}
    if not (subs & CHECKED) and not GH_API_COMMENT.search(command):
        return 0

    bare: list[str] = []
    for text in bodies(command):
        bare += _titles.bare_numbers(text)
    bare = sorted(set(bare), key=lambda s: int(s[1:]))
    if not bare:
        return 0

    print(
        "Rewrite the comment before posting it: "
        + ", ".join(bare)
        + " each cite an issue without saying what it is.\n\n"
        "`CLAUDE.md` says the rule covers replies, issue comments and "
        "documents alike. A comment is read in a terminal and in a "
        "notification mail, where a bare number carries nothing -- unlike an "
        "issue *description*, which Donald has ruled is read on the web and "
        "is exempt.\n\n"
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
