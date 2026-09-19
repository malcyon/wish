#!/usr/bin/env python3
"""Tell Donald once when a session's context passes a size worth knowing about.

Claude Code never shows the orchestrator its own context size, but the
number is in the transcript: every assistant turn Claude Code writes to the
session's `.jsonl` carries a `usage` block, and the sum of its
`input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens`
is the context the model was sent on that turn.

This is a `PreToolUse` hook on `Agent`, `Task` and `SendMessage`. It reads
the last recorded context total from the transcript and, the first time it
passes the line, writes a JSON object with a `systemMessage` field to
stdout, which Claude Code shows Donald as a one-line notice. It never
refuses the tool call -- the session keeps going, and Claude Code compacts
the context itself when the window fills.

The line is 400,000 tokens; `WISH_HANDOFF_TOKENS` overrides it, for a
session Donald wants a different number for, or a test.

Once a session's context has passed the line, an empty file under the temp
directory (`sticky_path`) stops it printing the notice again, even if a
later compaction brings the measured context back under the line.
"""
import json
import os
import sys
import tempfile

DEFAULT_LIMIT = 400_000

#: Tools that give a subagent work. Claude Code names the launcher `Agent`
#: today and named it `Task` before that; `SendMessage` resumes a finished
#: agent with more work, which is a launch by another door.
SPAWN_TOOLS = {"Agent", "Task", "SendMessage"}

#: Once a session has printed the notice, it stays printed: a compaction can
#: bring the measured context back under the line, and the notice is a
#: one-time thing, not a status the hook keeps re-announcing. One empty file
#: per session. Computed rather than taken from `tools.registry.scratch.scratch_dir`,
#: because the harness runs this hook under the system interpreter with the
#: repository on no path; it must stay equal to
#: `scratch.scratch_dir("notify-context-size")`.
STICKY_DIR = os.path.join("wish", "notify-context-size")

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


def notice(tokens: int, cap: int) -> str:
    return json.dumps({"systemMessage": (
        f"Context passed {cap:,} tokens (measured {tokens:,}). The session "
        "continues; Claude Code compacts when the window fills.")})


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
    sticky = sticky_path(payload)
    if sticky and os.path.exists(sticky):
        return 0
    path = payload.get("transcript_path")
    if not path:
        return 0
    cap = limit()
    tokens = last_context(path)
    if tokens is None or tokens < cap:
        return 0
    if sticky:
        try:
            os.makedirs(os.path.dirname(sticky), exist_ok=True)
            open(sticky, "a").close()
        except OSError:
            pass
    print(notice(tokens, cap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
