#!/usr/bin/env python3
"""Prove that Wish's three Codex guards are enabled and trusted."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TextIO

EXPECTED = {
    "check-issue-reads.py",
    "check-issue-writes.py",
    "check-push-tested.py",
}
TIMEOUT_SECONDS = 10


class CheckError(RuntimeError):
    """The app server could not prove the guards are live."""


def _send(stream: TextIO, message: dict[str, Any]) -> None:
    stream.write(json.dumps(message, separators=(",", ":")) + "\n")
    stream.flush()


def _response(
    process: subprocess.Popen[str], request_id: int
) -> dict[str, Any]:
    if process.stdout is None:
        raise CheckError("Codex app server has no output stream.")

    deadline = time.monotonic() + TIMEOUT_SECONDS
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CheckError("Codex app server timed out while listing hooks.")
            if not selector.select(remaining):
                raise CheckError("Codex app server timed out while listing hooks.")
            line = process.stdout.readline()
            if not line:
                detail = ""
                if process.stderr is not None:
                    detail = process.stderr.read().strip()
                suffix = f" {detail}" if detail else ""
                raise CheckError(f"Codex app server stopped before replying.{suffix}")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise CheckError(
                    "Codex app server rejected the hook check: "
                    + json.dumps(message["error"], separators=(",", ":"))
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise CheckError("Codex app server returned no hook-check result.")
            return result
    finally:
        selector.close()


def _listed_hooks(root: Path) -> list[dict[str, Any]]:
    try:
        process = subprocess.Popen(
            ["codex", "app-server", "--listen", "stdio://"],
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise CheckError(f"Cannot start Codex app server: {exc}") from exc

    try:
        if process.stdin is None:
            raise CheckError("Codex app server has no input stream.")
        _send(
            process.stdin,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "wish-hook-check", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            },
        )
        _response(process, 1)
        _send(process.stdin, {"method": "initialized", "params": {}})
        _send(
            process.stdin,
            {
                "id": 2,
                "method": "hooks/list",
                "params": {"cwds": [os.fspath(root)]},
            },
        )
        result = _response(process, 2)
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    entries = result.get("data")
    if not isinstance(entries, list) or len(entries) != 1:
        raise CheckError("Codex app server returned no hook list for this repository.")
    entry = entries[0]
    if not isinstance(entry, dict):
        raise CheckError("Codex app server returned an invalid hook list.")
    errors = entry.get("errors")
    if errors:
        raise CheckError(
            "Codex reported a hook configuration error: "
            + json.dumps(errors, separators=(",", ":"))
        )
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        raise CheckError("Codex app server returned an invalid hook list.")
    return [hook for hook in hooks if isinstance(hook, dict)]


def _guard_name(hook: dict[str, Any], source: Path) -> str | None:
    if hook.get("sourcePath") != os.fspath(source):
        return None
    command = hook.get("command")
    if not isinstance(command, str):
        return None
    return next((name for name in EXPECTED if name in command), None)


def check(root: Path) -> None:
    source = root / ".codex" / "hooks.json"
    found: dict[str, dict[str, Any]] = {}
    for hook in _listed_hooks(root):
        name = _guard_name(hook, source)
        if name is not None:
            found[name] = hook

    missing = EXPECTED - found.keys()
    if missing:
        raise CheckError("Missing Codex guards: " + ", ".join(sorted(missing)) + ".")

    bad = []
    for name in sorted(EXPECTED):
        hook = found[name]
        reasons = []
        if hook.get("eventName") != "preToolUse" or hook.get("matcher") != "Bash":
            reasons.append("not a Bash PreToolUse hook")
        if hook.get("enabled") is not True:
            reasons.append("disabled")
        if hook.get("trustStatus") != "trusted":
            reasons.append(str(hook.get("trustStatus", "unknown trust state")))
        if reasons:
            bad.append(f"{name} ({', '.join(reasons)})")
    if bad:
        raise CheckError("Codex guards are not live: " + "; ".join(bad) + ".")


def main() -> int:
    root = Path(__file__).resolve().parents[4]
    try:
        check(root)
    except CheckError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Codex guards are enabled and trusted: " + ", ".join(sorted(EXPECTED)) + ".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
