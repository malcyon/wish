"""`.claude/hooks/check-push-tested.py` is retired: it checks nothing and no wiring registers it.

The file stays so that a session with cached hook wiring does not fail on
every Bash call. CI is the full-suite gate (`.claude/rules/commits.md`).
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "check-push-tested.py"


def _commands(config: dict) -> list[str]:
    return [h["command"]
            for groups in config.get("hooks", {}).values()
            for group in groups
            for h in group["hooks"]]


def test_neither_wiring_registers_it():
    """Claude Code reads `.claude/settings.json`; Codex reads `.codex/hooks.json`."""
    for path in (ROOT / ".claude" / "settings.json", ROOT / ".codex" / "hooks.json"):
        commands = _commands(json.loads(path.read_text(encoding="utf-8")))
        assert commands, path
        assert not any("check-push-tested" in c for c in commands), path


@pytest.mark.parametrize("command", [
    "git push",
    "git commit --allow-empty -m x && git push",
    "git status",
])
def test_it_lets_every_command_through(command):
    """A session with the old wiring cached must not be refused anything."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    done = subprocess.run([sys.executable, str(HOOK)], input=payload,
                          capture_output=True, text=True, timeout=30,
                          env=os.environ | {"HOME": str(ROOT / "nonexistent")})
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""
    assert done.stderr == ""
