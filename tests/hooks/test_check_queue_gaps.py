"""`.claude/hooks/check-queue-gaps.py` blocks a wakeup while the queue has gaps.

A `PreToolUse` hook on `ScheduleWakeup`: it runs `queuegap.py` and exits 2
with the gap lines when it prints anything but its no-gaps line, and lets the
call through when the loop is ending, when the Plane runtime is missing or
when queuegap fails or times out.
"""
import importlib.util
import io
import json
import pathlib
import sys

import pytest

HOOK = (pathlib.Path(__file__).resolve().parents[2]
        / ".claude" / "hooks" / "check-queue-gaps.py")
GAP = "Queue: WISH-12 has no live agent and no reason."


def _module():
    spec = importlib.util.spec_from_file_location("_check_queue_gaps", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A fake Plane runtime whose queuegap.py runs the given Python body."""
    mod = _module()
    config = tmp_path / "config.json"
    config.write_text("{}")
    script = tmp_path / "tools" / "plane" / "queuegap.py"
    script.parent.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(mod, "plane_python", lambda: sys.executable)
    monkeypatch.setattr(mod, "plane_config", lambda: str(config))

    def install(body):
        script.write_text(body)
        return mod
    return install


def run(monkeypatch, mod, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return mod.main()


WAKEUP = {"tool_name": "ScheduleWakeup", "tool_input": {"delaySeconds": 60}}


def test_gaps_block_and_are_shown(fake, monkeypatch, capsys):
    mod = fake(f"print({GAP!r})\n")
    assert run(monkeypatch, mod, WAKEUP) == 2
    err = capsys.readouterr().err
    assert GAP in err
    assert "reason" in err


def test_no_gaps_line_passes(fake, monkeypatch, capsys):
    mod = fake("print('No gaps.')\n")
    assert run(monkeypatch, mod, WAKEUP) == 0
    assert capsys.readouterr().err == ""


def test_stop_true_passes_without_running_queuegap(fake, monkeypatch):
    mod = fake(f"print({GAP!r})\n")
    payload = {"tool_name": "ScheduleWakeup", "tool_input": {"stop": True}}
    assert run(monkeypatch, mod, payload) == 0


def test_missing_runtime_passes_with_warning(fake, monkeypatch, capsys):
    mod = fake(f"print({GAP!r})\n")
    monkeypatch.setattr(mod, "plane_python", lambda: "/nonexistent/python")
    assert run(monkeypatch, mod, WAKEUP) == 0
    assert "skipped" in capsys.readouterr().err


def test_queuegap_error_passes_with_warning(fake, monkeypatch, capsys):
    mod = fake("import sys\nsys.exit(3)\n")
    assert run(monkeypatch, mod, WAKEUP) == 0
    assert "skipped" in capsys.readouterr().err


def test_timeout_passes_with_warning(fake, monkeypatch, capsys):
    mod = fake("import time\ntime.sleep(10)\n")
    monkeypatch.setattr(mod, "TIMEOUT_SECONDS", 1)
    assert run(monkeypatch, mod, WAKEUP) == 0
    assert "skipped" in capsys.readouterr().err


def test_other_tools_are_not_affected(fake, monkeypatch, capsys):
    mod = fake(f"print({GAP!r})\n")
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert run(monkeypatch, mod, payload) == 0
    assert capsys.readouterr().err == ""
