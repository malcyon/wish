#!/usr/bin/env python3
"""Refuse a new worker subagent once the session's context has passed the hand-off line.

`.claude/skills/orchestrate/SKILL.md` tells the orchestrator to hand off at
about 300k tokens of context: launch nothing new, let the agents in flight
report, commit, push, and tell Donald to start a fresh session. **The rule
did not hold, and could not have**: the orchestrator is never shown its own
context size, so it was asked to act on a number it does not have. On
2026-09-16 the running orchestrator went 479 turns past the line, and those
turns were most of what the day cost, because every turn resends the whole
context.

The number is in the transcript. Every assistant turn Claude Code writes to
the session's `.jsonl` carries a `usage` block, and the sum of its
`input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens`
is the context the model was sent on that turn -- 677,820 for that
orchestrator's last turn, where the harness showed 669k. A `PreToolUse` hook
is handed `transcript_path`, so it can read what the model cannot.

So this is a `PreToolUse` hook on the `Agent` tool. It takes the last
recorded context total from the transcript, and past the line it refuses the
spawn with exit 2, and its stderr -- which goes back to the assistant as the
tool's result -- says what to do instead. `code-reviewer` and `test-runner`
are let through, because the wind-down still has to review the last commits
and run the suite before the push.

The line is 300,000 tokens; `WISH_HANDOFF_TOKENS` overrides it, for a
session Donald wants to run longer or a test that wants a smaller number.

**This is a tripwire, not a boundary.** It measures the context at the last
completed turn, not the current one; the refusal itself and the turns that
wind down still cost their full context each; and a session with no
`transcript_path`, or a transcript with no usage recorded, is let through.
It exists so the orchestrator finds out, at the one moment it matters, that
the line is behind it.
"""
import json
import os
import sys

DEFAULT_LIMIT = 300_000

#: Only tools that start a subagent are refused. Claude Code names the tool
#: `Agent` today and named it `Task` before that.
SPAWN_TOOLS = {"Agent", "Task"}

#: The wind-down needs these two: the review of the last commits and the one
#: suite run before the push. Everything else is new work.
ALLOWED_PAST_THE_LINE = {"code-reviewer", "test-runner"}

#: The transcript is read from the end, in chunks this size, until a turn
#: with a usage block has been seen. One assistant turn is far smaller.
CHUNK = 1 << 20


def limit() -> int:
    raw = os.environ.get("WISH_HANDOFF_TOKENS", "")
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_LIMIT


def context_of(record: dict) -> int | None:
    """The context a recorded assistant turn was sent, or None if not one."""
    if record.get("type") != "assistant":
        return None
    usage = (record.get("message") or {}).get("usage") or {}
    total = sum(usage.get(k) or 0 for k in (
        "input_tokens", "cache_read_input_tokens",
        "cache_creation_input_tokens"))
    # A turn that was interrupted mid-stream records a usage block of zeros.
    return total or None


def last_context(path: str) -> int | None:
    """The context of the last completed assistant turn in a transcript.

    Read backwards in chunks so a 70MB transcript costs the same as a small
    one; the answer is always within the last few lines.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            tail = b""
            pos = size
            while pos > 0:
                step = min(CHUNK, pos)
                pos -= step
                fh.seek(pos)
                tail = fh.read(step) + tail
                lines = tail.split(b"\n")
                # The first line may be a partial one from the chunk boundary
                # -- skip it unless the whole file has been read.
                first = 0 if pos == 0 else 1
                for line in reversed(lines[first:]):
                    if not line.strip():
                        continue
                    try:
                        found = context_of(json.loads(line))
                    except ValueError:
                        continue
                    if found:
                        return found
                # Nothing yet: keep the partial first line and read on.
                tail = lines[0] if first else b""
    except OSError:
        return None
    return None


def refusal(tokens: int, cap: int) -> str:
    return (
        f"Refused: this session's context is {tokens:,} tokens, past the "
        f"{cap:,} hand-off line in .claude/skills/orchestrate/SKILL.md. "
        "Every turn resends all of it. Launch no new work. Let the agents "
        "already in flight report, commit their work, run code-reviewer and "
        "test-runner (both are still allowed), push, commit the queue file, "
        "stop the loop with ScheduleWakeup stop:true, and tell Donald to "
        "start a fresh session with /orchestrate. Only code-reviewer and "
        "test-runner may be launched now.\n")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if payload.get("tool_name") not in SPAWN_TOOLS:
        return 0
    agent = (payload.get("tool_input") or {}).get("subagent_type", "")
    if agent in ALLOWED_PAST_THE_LINE:
        return 0
    path = payload.get("transcript_path")
    if not path:
        return 0
    tokens = last_context(path)
    cap = limit()
    if tokens is None or tokens < cap:
        return 0
    sys.stderr.write(refusal(tokens, cap))
    return 2


if __name__ == "__main__":
    sys.exit(main())
