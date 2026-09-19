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

`SendMessage` is refused too, because a message to a finished agent gives it
more work without a launch, and once refused a session stays refused, by an
empty file under the temp directory (`sticky_path`), so a compaction that brings the measured
context back under the line does not turn the wind-down back into a working
session.

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
import tempfile

DEFAULT_LIMIT = 300_000

#: Tools that give a subagent work. Claude Code names the launcher `Agent`
#: today and named it `Task` before that; `SendMessage` resumes a finished
#: agent with more work, which is a launch by another door.
SPAWN_TOOLS = {"Agent", "Task", "SendMessage"}

#: Once a session has been refused, it stays refused: a compaction can bring
#: the measured context back under the line, and the wind-down must not turn
#: back into a working session because of it. One empty file per session.
#: Computed rather than taken from `tools.registry.scratch.scratch_dir`, because the
#: harness runs this hook under the system interpreter with the repository on
#: no path; it must stay equal to `scratch.scratch_dir("check-context-handoff")`.
STICKY_DIR = os.path.join("wish", "check-context-handoff")

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


def refusal(tokens: int, cap: int, resumed: bool = False,
            already: bool = False) -> str:
    if already:
        head = ("Refused: this session is winding down; it passed the "
                f"{cap:,} hand-off line earlier and stays past it. ")
    else:
        head = (f"Refused: this session's context is {tokens:,} tokens, past "
                f"the {cap:,} hand-off line in "
                ".claude/skills/orchestrate/SKILL.md. Every turn resends all "
                "of it. ")
    what = ("A message to a finished agent is new work by another door. "
            if resumed else "")
    return (
        head + what +
        "Launch no new work and resume no finished agent. Let the agents "
        "already in flight report, commit their work, run code-reviewer and "
        "test-runner (both are still allowed), push, stop the loop with "
        "ScheduleWakeup stop:true, and tell Donald to start a fresh session "
        "with /orchestrate.\n")


def sticky_path(payload: dict) -> str | None:
    session = payload.get("session_id")
    if not session:
        return None
    # A session id is a file name; one that is absolute or holds `..` must not
    # point the marker anywhere but under the sticky directory.
    name = os.path.basename(str(session))
    if name in ("", ".", ".."):
        return None
    return os.path.join(tempfile.gettempdir(), STICKY_DIR, name)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    tool = payload.get("tool_name")
    if tool not in SPAWN_TOOLS:
        return 0
    agent = (payload.get("tool_input") or {}).get("subagent_type", "")
    if tool != "SendMessage" and agent in ALLOWED_PAST_THE_LINE:
        return 0
    sticky = sticky_path(payload)
    cap = limit()
    if sticky and os.path.exists(sticky):
        sys.stderr.write(refusal(cap, cap, resumed=(tool == "SendMessage"),
                                 already=True))
        return 2
    path = payload.get("transcript_path")
    if not path:
        return 0
    tokens = last_context(path)
    if tokens is None or tokens < cap:
        return 0
    if sticky:
        try:
            os.makedirs(os.path.dirname(sticky), exist_ok=True)
            open(sticky, "a").close()
        except OSError:
            pass
    sys.stderr.write(refusal(tokens, cap, resumed=(tool == "SendMessage")))
    return 2


if __name__ == "__main__":
    sys.exit(main())
