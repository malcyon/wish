#!/usr/bin/env python3
"""Refuse the orchestrator's own edits to a repository file.

`.claude/skills/orchestrate/SKILL.md` tells the orchestrator it never edits
files itself -- every change goes to a subagent. The rule alone does not
hold: fixing a reviewer's finding by hand is the shortest path in the
moment, and it is also what turns a review into a loop of four or more
passes against the orchestrator's own edits.

This is a `PreToolUse` hook on `Edit`, `Write`, `MultiEdit` and
`NotebookEdit`. It refuses with exit 2, and its stderr -- which goes back to
the assistant as the tool's result -- says to send the change out instead,
when all three hold:

  * the call is the main window's, not a subagent's: a subagent's call
    carries an `agent_id` in the payload, and Claude Code hands it the main
    session's `transcript_path`, so that path alone cannot tell the two
    apart; a `transcript_path` with a `subagents` component is a subagent's
    too;
  * the transcript has, at some point, shown the orchestrate skill's opening
    sentence, "You are the orchestrator for this session" -- which enters it
    when the skill is invoked or its file is read;
  * the file being edited is inside the repository, found from
    `CLAUDE_PROJECT_DIR` or, failing that, the git root of the session's
    working directory -- so a scratch file under `/tmp` or `~/.cache` stays
    allowed.

Anything missing -- no `transcript_path`, an unreadable transcript, no
repository root found -- lets the edit through: a hook with nothing to go on
refuses nothing.

Scanning the whole transcript for the marker has to be cheap enough to run
on every edit, so the answer is cached in a stamp file under the temp
directory, keyed by a hash of the transcript path -- one read per session
rather than one per edit. The marker, once seen, does not go away even if a
later compaction drops it from the window the model is actually sent, so the
cache is never invalidated once written.

**This is a tripwire, not a boundary.** A session that invokes the
orchestrate skill only after its first edit is not yet caught by a cached
"no marker seen" answer from that earlier edit; it exists to catch the
ordinary case, where the skill's sentence is already in the transcript
before the orchestrator's first tool call.
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

#: The marker the orchestrate skill's opening line carries, in both
#: `.claude/skills/orchestrate/SKILL.md` and its Codex twin.
MARKER = "You are the orchestrator for this session"

#: Tools that write a repository file directly.
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

#: One directory under the temp directory, holding one stamp file per
#: transcript this hook has already scanned for the marker.
STICKY_DIR = os.path.join("wish", "check-orchestrator-edits")


def edited_path(payload: dict) -> str | None:
    """The file the call would write, or `None` if the input names none."""
    tool_input = payload.get("tool_input") or {}
    key = "notebook_path" if payload.get("tool_name") == "NotebookEdit" else "file_path"
    path = tool_input.get(key)
    return path or None


def is_subagent(payload: dict) -> bool:
    """Whether the call is a subagent's rather than the main window's.

    Claude Code adds `agent_id` to a hook payload only inside a subagent
    call, and gives that call the main session's `transcript_path`, so the
    path is checked second and only catches a transcript that lives under a
    `subagents` directory.
    """
    if payload.get("agent_id"):
        return True
    transcript_path = payload.get("transcript_path") or ""
    return "subagents" in pathlib.PurePath(transcript_path).parts


def _git_root(cwd: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=cwd,
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def repository_root(cwd: str) -> str | None:
    """`CLAUDE_PROJECT_DIR`, or the git root of `cwd` if that is unset."""
    return os.environ.get("CLAUDE_PROJECT_DIR") or _git_root(cwd)


def inside_repository(file_path: str, cwd: str) -> bool:
    root = repository_root(cwd)
    if not root:
        return False
    try:
        target = pathlib.Path(file_path).resolve()
        base = pathlib.Path(root).resolve()
    except OSError:
        return False
    return target == base or base in target.parents


def stamp_path(transcript_path: str) -> str:
    """`<tmp>/wish/check-orchestrator-edits/<hash of transcript_path>`."""
    digest = hashlib.sha256(transcript_path.encode("utf-8", "surrogateescape")).hexdigest()
    return os.path.join(tempfile.gettempdir(), STICKY_DIR, digest)


def is_orchestrator(transcript_path: str) -> bool:
    """Whether the transcript has ever shown the orchestrate skill's opening line.

    Reads the stamp first, so a transcript this hook has already scanned
    costs one small file read instead of a scan of the whole session.
    """
    stamp = stamp_path(transcript_path)
    try:
        with open(stamp, encoding="utf-8") as fh:
            return fh.read() == "1"
    except OSError:
        pass
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            found = MARKER in fh.read()
    except OSError:
        return False
    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write("1" if found else "0")
    except OSError:
        pass
    return found


def refusal(file_path: str) -> str:
    return (
        f"Refused: the orchestrator does not edit files, and {file_path} is "
        "one. Send this change to a junior-dev brief instead -- back to the "
        "agent that made it, or to a new one, with the reviewer's finding "
        "as the brief.\n"
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if payload.get("tool_name") not in EDIT_TOOLS:
        return 0
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return 0
    if is_subagent(payload):
        return 0
    file_path = edited_path(payload)
    if not file_path:
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    if not inside_repository(file_path, cwd):
        return 0
    if not is_orchestrator(transcript_path):
        return 0
    sys.stderr.write(refusal(file_path))
    return 2


if __name__ == "__main__":
    sys.exit(main())
