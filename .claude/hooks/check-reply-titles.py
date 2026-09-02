#!/usr/bin/env python3
"""Refuse the next tool call when the prose already said a bare `#59`.

`check-issue-titles.py` is a `Stop` hook, so it only inspects a turn once the
turn has ended. Donald reads the text as it streams, and a turn that says
something and then goes on making tool calls has already put a bare number in
front of him before that hook ever runs. Every catch on 2026-09-02 was a
turn-final message; every miss was a mid-turn one.

Donald, that day, of the third miss: *"You just did it again."*

This is a `PreToolUse` hook on every tool. It reads the same transcript and
applies the same rule to everything the assistant has said **so far this
turn**, and exits 2 -- refusing the call -- when any of it cites an issue
without saying what it is.

**It cannot unsend.** Text is on his screen before any hook sees it, so this
catches the fault one beat later rather than preventing it, and the real
guard is still writing the title the first time. What it does buy is that the
mistake stops the turn at once instead of surviving to the end of it, and
that the correction happens while the sentence is still on screen.

Once it fires it will keep firing for the rest of the turn, because the text
it is reading cannot be taken back. That is deliberate: the way out is to end
the turn and say it again properly, which is the behaviour being asked for.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location(
    "_titles", os.path.join(HERE, "check-issue-titles.py"))
_titles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_titles)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                        # never block on a malformed payload

    path = payload.get("transcript_path")
    if not path:
        return 0                        # nothing to read; do not block work
    try:
        text = _titles.last_assistant_text(path)
    except OSError:
        return 0

    bare = _titles.bare_numbers(text)
    if not bare:
        return 0

    print(
        "Stop and correct what you have already said this turn: "
        + ", ".join(bare)
        + " each cite an issue without saying what it is.\n\n"
        "A bare number makes Donald look it up: fast for you, slow for him. "
        "This is a mid-turn check, so the sentence is on his screen already "
        "-- end the turn and say it again with the title, rather than "
        "carrying on.\n\n"
        "    #59 (Map the DOS saved game, not just the character record)\n\n"
        "Get each title with:\n"
        "    gh issue view N --json number,title -q '\"#\\(.number) "
        '(\\(.title))"\'',
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
