"""`.claude/hooks/check-context-handoff.py` refuses a new worker once the context passes the hand-off line.

`.claude/skills/orchestrate/SKILL.md` says to hand off at 400k tokens, but the
model is never shown its own context size. The transcript records it on
every assistant turn, and this hook reads it from there and refuses the
launch that the rule alone cannot stop.
"""
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

WINDOWS = os.name == "nt"
HOOK = (pathlib.Path(__file__).resolve().parents[1]
        / ".claude" / "hooks" / "check-context-handoff.py")


def _module():
    """Load the hook by path -- a hyphenated filename is not importable."""
    spec = importlib.util.spec_from_file_location("_check_context_handoff", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _turn(kind, **usage):
    return json.dumps({"type": kind, "message": {"usage": usage}})


def transcript(tmp_path, *lines):
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def run(monkeypatch, payload):
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return mod.main()


def spawn(path, agent="junior-dev", tool="Agent", session=None):
    payload = {"tool_name": tool, "transcript_path": path,
               "tool_input": {"subagent_type": agent, "prompt": "x"}}
    if session:
        payload["session_id"] = session
    return payload


def test_the_context_is_the_sum_of_the_three_input_counts(tmp_path, monkeypatch):
    """677,820 on the 2026-09-16 orchestrator's last turn: 2 + 676,706 + 1,112."""
    mod = _module()
    path = transcript(tmp_path, _turn(
        "assistant", input_tokens=2, cache_read_input_tokens=676_706,
        cache_creation_input_tokens=1_112, output_tokens=40))
    assert mod.last_context(path) == 677_820


def test_a_session_past_the_line_is_refused(tmp_path, monkeypatch, capsys):
    path = transcript(tmp_path, _turn(
        "assistant", input_tokens=32, cache_read_input_tokens=400_000))
    assert run(monkeypatch, spawn(path)) == 2
    err = capsys.readouterr().err
    assert "400,032" in err
    assert "/orchestrate" in err
    assert "ScheduleWakeup stop:true" in err


def test_a_session_under_the_line_is_let_through(tmp_path, monkeypatch):
    path = transcript(tmp_path, _turn(
        "assistant", input_tokens=32, cache_read_input_tokens=399_000))
    assert run(monkeypatch, spawn(path)) == 0


def test_the_last_turn_counts_not_the_largest(tmp_path, monkeypatch):
    """A session that was compacted is under the line again."""
    path = transcript(
        tmp_path,
        _turn("assistant", cache_read_input_tokens=500_000),
        _turn("assistant", cache_read_input_tokens=90_000))
    assert run(monkeypatch, spawn(path)) == 0


def test_a_turn_recorded_as_zero_is_skipped(tmp_path, monkeypatch):
    """An interrupted turn records a usage block of zeros; it is not an answer."""
    path = transcript(
        tmp_path,
        _turn("assistant", cache_read_input_tokens=500_000),
        json.dumps({"type": "user", "message": {"content": "x"}}),
        _turn("assistant", input_tokens=0, cache_read_input_tokens=0))
    assert run(monkeypatch, spawn(path)) == 2


def test_the_wind_down_agents_are_still_allowed(tmp_path, monkeypatch):
    """The hand-off still reviews the last commits and runs the suite."""
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=600_000))
    assert run(monkeypatch, spawn(path, "code-reviewer")) == 0
    assert run(monkeypatch, spawn(path, "test-runner")) == 0
    assert run(monkeypatch, spawn(path, "senior-analyst")) == 2


def test_a_message_to_a_finished_agent_is_refused_past_the_line(tmp_path, monkeypatch, capsys):
    """SendMessage resumes an agent with more work, which is a launch by another door."""
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=600_000))
    message = {"tool_name": "SendMessage", "transcript_path": path,
               "tool_input": {"to": "a1b2c3", "message": "one more ticket"}}
    assert run(monkeypatch, message) == 2
    assert "finished agent" in capsys.readouterr().err
    under = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=100_000))
    message["transcript_path"] = under
    assert run(monkeypatch, message) == 0


def test_once_refused_a_session_stays_refused(tmp_path, monkeypatch, capsys):
    """A compaction can bring the measured context back under the line."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    over = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=600_000))
    assert run(monkeypatch, spawn(over, session="s1")) == 2
    assert (tmp_path / "wish" / "check-context-handoff" / "s1").exists()
    compacted = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=90_000))
    assert run(monkeypatch, spawn(compacted, session="s1")) == 2
    assert "winding down" in capsys.readouterr().err
    # The wind-down agents still get through, and another session is untouched.
    assert run(monkeypatch, spawn(compacted, "test-runner", session="s1")) == 0
    assert run(monkeypatch, spawn(compacted, session="s2")) == 0


@pytest.mark.parametrize("session", ["/tmp/elsewhere/s1", "../x", "a/../../x"])
def test_a_session_id_cannot_move_the_marker_out_of_its_directory(
        tmp_path, monkeypatch, session):
    """The id is the harness's, but the marker is a file the hook creates, so
    an absolute or `..` id must land under the sticky directory or not at all."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    over = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=600_000))
    assert run(monkeypatch, spawn(over, session=session)) == 2
    sticky = tmp_path / "wish" / "check-context-handoff"
    assert sticky.is_dir()
    made = [p for p in tmp_path.rglob("*") if p.is_file() and p.name != "session.jsonl"]
    assert made and all(sticky in p.parents for p in made)


def test_a_session_id_that_is_only_dots_makes_no_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    over = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=600_000))
    for session in ("..", "a/.."):
        assert run(monkeypatch, spawn(over, session=session)) == 2
    assert not (tmp_path / "wish").exists()


def test_the_sticky_directory_is_the_one_scratch_names(tmp_path, monkeypatch):
    """The hook cannot import `tools.registry.scratch` (the system interpreter has no
    repository on its path), so nothing else keeps the two spellings equal."""
    from tools.registry import scratch
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    mod = _module()
    ours = pathlib.Path(mod.sticky_path({"session_id": "abc"}))
    assert ours == scratch.scratch_dir("check-context-handoff", "abc")


def test_the_older_tool_name_is_matched_too(tmp_path, monkeypatch):
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=600_000))
    assert run(monkeypatch, spawn(path, tool="Task")) == 2


def test_other_tools_and_missing_transcripts_are_let_through(tmp_path, monkeypatch):
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=600_000))
    assert run(monkeypatch, spawn(path, tool="Bash")) == 0
    assert run(monkeypatch, {"tool_name": "Agent", "tool_input": {}}) == 0
    assert run(monkeypatch, spawn(str(tmp_path / "gone.jsonl"))) == 0


def test_the_line_can_be_moved_with_the_environment(tmp_path, monkeypatch):
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=50_000))
    monkeypatch.setenv("WISH_HANDOFF_TOKENS", "40000")
    assert run(monkeypatch, spawn(path)) == 2
    monkeypatch.setenv("WISH_HANDOFF_TOKENS", "not a number")
    assert run(monkeypatch, spawn(path)) == 0


def test_a_large_transcript_is_read_from_the_end(tmp_path, monkeypatch):
    """The answer is in the last few lines; the read must not depend on size."""
    mod = _module()
    filler = json.dumps({"type": "user", "message": {"content": "y" * 100_000}})
    lines = [_turn("assistant", cache_read_input_tokens=10)]
    lines += [filler] * 30
    lines.append(_turn("assistant", cache_read_input_tokens=310_000))
    lines += [filler] * 12  # more than one chunk of tool results after it
    path = transcript(tmp_path, *lines)
    assert os.path.getsize(path) > 2 * mod.CHUNK
    assert mod.last_context(path) == 310_000


def test_the_hook_is_registered_on_the_agent_tool():
    """An unregistered hook guards nothing."""
    root = pathlib.Path(__file__).resolve().parents[1]
    claude = json.loads((root / ".claude" / "settings.json").read_text())
    groups = [g for g in claude["hooks"].get("PreToolUse", [])
              if any("check-context-handoff.py" in h["command"] for h in g["hooks"])]
    assert groups, "not wired into .claude/settings.json"
    assert "Agent" in groups[0]["matcher"]
    assert "SendMessage" in groups[0]["matcher"]


def test_the_skill_names_the_hook():
    """The orchestrator is told what the refusal means, before it sees one."""
    root = pathlib.Path(__file__).resolve().parents[1]
    skill = (root / ".claude" / "skills" / "orchestrate" / "SKILL.md").read_text()
    assert "check-context-handoff.py" in skill
    assert "ScheduleWakeup stop:true" in skill


@pytest.mark.skipif(WINDOWS, reason="/usr/bin/python3 does not exist on Windows")
def test_the_hook_runs_under_the_system_interpreter(tmp_path):
    """The harness runs it, not `.venv`, so it must be standard library only."""
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=600_000))
    done = subprocess.run(
        ["/usr/bin/python3", str(HOOK)], input=json.dumps(spawn(path)),
        capture_output=True, text=True, timeout=30)
    assert done.returncode == 2, done.stderr
    assert "hand-off line" in done.stderr
