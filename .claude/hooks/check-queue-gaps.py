#!/usr/bin/env python3
"""Block a `ScheduleWakeup` call while the queue has gaps.

The orchestrate skill says to act on every ticket with no live agent and no
recorded reason before sleeping. This `PreToolUse` hook on `ScheduleWakeup`
runs `tools/plane/queuegap.py` under the Plane runtime and, when it prints
anything other than its no-gaps line, exits 2 with the gap lines on stderr,
which Claude Code returns to the assistant as the tool's result.

It lets the call through when the input has `stop: true` (ending the loop)
and when the Plane runtime, its config or queuegap is missing, fails or
times out, printing a one-line warning: a hook with nothing to go on must
not trap a session.
"""
import json
import os
import pathlib
import subprocess
import sys

TOOL = "ScheduleWakeup"
NO_GAPS = "No gaps."
TIMEOUT_SECONDS = 30


def plane_python() -> str:
    return os.path.join(os.path.expanduser("~"), ".local", "share", "wish", "plane-venv", "bin", "python")


def plane_config() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "wish-plane", "config.json")


def repository_root() -> str:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return env or str(pathlib.Path(__file__).resolve().parents[2])


def warn(message: str) -> None:
    sys.stderr.write(f"Queue gap check skipped: {message}\n")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if payload.get("tool_name") != TOOL:
        return 0
    if (payload.get("tool_input") or {}).get("stop") is True:
        return 0
    python, config = plane_python(), plane_config()
    if not os.path.exists(python) or not os.path.exists(config):
        warn("the Plane runtime or its config is missing.")
        return 0
    script = os.path.join(repository_root(), "tools", "plane", "queuegap.py")
    env = dict(os.environ, WISH_PLANE_CONFIG=config)
    try:
        done = subprocess.run(
            [python, script], capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, env=env, cwd=repository_root())
    except subprocess.TimeoutExpired:
        warn(f"queuegap.py took longer than {TIMEOUT_SECONDS} seconds.")
        return 0
    except OSError as exc:
        warn(f"queuegap.py could not run ({exc}).")
        return 0
    if done.returncode != 0:
        warn(f"queuegap.py failed with exit {done.returncode}.")
        return 0
    output = done.stdout.strip()
    if not output or output == NO_GAPS:
        return 0
    sys.stderr.write(
        f"{output}\n"
        "Wakeup blocked: start an agent, record a reason, or fix the Plane "
        "state for each line above before scheduling a wakeup.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
