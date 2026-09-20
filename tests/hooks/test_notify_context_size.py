"""`.claude/hooks/notify-context-size.py` tells Donald once when the context passes a line.

`.claude/skills/orchestrate/SKILL.md` says the orchestrator neither sees nor
acts on this; it exists only so Donald gets one notice, printed as a
`systemMessage` Claude Code shows him, from a hook that otherwise never
refuses the tool call it watches.
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
HOOK = (pathlib.Path(__file__).resolve().parents[2]
        / ".claude" / "hooks" / "notify-context-size.py")


def _module():
    """Load the hook by path -- a hyphenated filename is not importable."""
    spec = importlib.util.spec_from_file_location("_notify_context_size", HOOK)
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
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    code = mod.main()
    return code, out.getvalue()


def spawn(path, tool="Agent", session=None):
    payload = {"tool_name": tool, "transcript_path": path,
               "tool_input": {"subagent_type": "junior-dev", "prompt": "x"}}
    if session:
        payload["session_id"] = session
    return payload


def test_the_context_is_the_sum_of_the_three_input_counts(tmp_path):
    mod = _module()
    path = transcript(tmp_path, _turn(
        "assistant", input_tokens=2, cache_read_input_tokens=676_706,
        cache_creation_input_tokens=1_112, output_tokens=40))
    assert mod.last_context(path) == 677_820


def test_a_session_under_the_line_prints_nothing(tmp_path, monkeypatch):
    path = transcript(tmp_path, _turn(
        "assistant", input_tokens=32, cache_read_input_tokens=399_000))
    code, out = run(monkeypatch, spawn(path))
    assert code == 0
    assert out == ""


def test_a_session_past_the_line_exits_zero_and_prints_the_notice_once(
        tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    path = transcript(tmp_path, _turn(
        "assistant", input_tokens=32, cache_read_input_tokens=400_000))
    payload = spawn(path, session="s1")
    code, out = run(monkeypatch, payload)
    assert code == 0
    message = json.loads(out)["systemMessage"]
    assert "400,000" in message
    assert "400,032" in message

    # A second call from the same session prints nothing more.
    code, out = run(monkeypatch, payload)
    assert code == 0
    assert out == ""


def test_the_last_turn_counts_not_the_largest(tmp_path, monkeypatch):
    """A session that was compacted is under the line again."""
    path = transcript(
        tmp_path,
        _turn("assistant", cache_read_input_tokens=500_000),
        _turn("assistant", cache_read_input_tokens=90_000))
    code, out = run(monkeypatch, spawn(path))
    assert code == 0
    assert out == ""


def test_a_turn_recorded_as_zero_is_skipped(tmp_path, monkeypatch):
    """An interrupted turn records a usage block of zeros; it is not an answer."""
    path = transcript(
        tmp_path,
        _turn("assistant", cache_read_input_tokens=500_000),
        json.dumps({"type": "user", "message": {"content": "x"}}),
        _turn("assistant", input_tokens=0, cache_read_input_tokens=0))
    code, out = run(monkeypatch, spawn(path))
    assert code == 0
    assert json.loads(out)["systemMessage"]


def test_the_older_tool_name_and_sendmessage_are_matched_too(tmp_path, monkeypatch):
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=500_000))
    for tool in ("Task", "SendMessage"):
        code, out = run(monkeypatch, spawn(path, tool=tool))
        assert code == 0
        assert json.loads(out)["systemMessage"]


def test_other_tools_and_missing_transcripts_print_nothing(tmp_path, monkeypatch):
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=500_000))
    code, out = run(monkeypatch, spawn(path, tool="Bash"))
    assert (code, out) == (0, "")
    code, out = run(monkeypatch, {"tool_name": "Agent", "tool_input": {}})
    assert (code, out) == (0, "")
    code, out = run(monkeypatch, spawn(str(tmp_path / "gone.jsonl")))
    assert (code, out) == (0, "")


def test_the_line_can_be_moved_with_the_environment(tmp_path, monkeypatch):
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=50_000))
    monkeypatch.setenv("WISH_HANDOFF_TOKENS", "40000")
    code, out = run(monkeypatch, spawn(path))
    assert code == 0
    assert json.loads(out)["systemMessage"]
    path2 = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=50_000))
    monkeypatch.setenv("WISH_HANDOFF_TOKENS", "not a number")
    code, out = run(monkeypatch, spawn(path2))
    assert (code, out) == (0, "")


def test_a_large_transcript_is_read_from_the_end(tmp_path):
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


@pytest.mark.parametrize("session", ["/tmp/elsewhere/s1", "../x", "a/../../x"])
def test_a_session_id_cannot_move_the_marker_out_of_its_directory(
        tmp_path, monkeypatch, session):
    """The id is the harness's, but the marker is a file the hook creates, so
    an absolute or `..` id must land under the sticky directory or not at all."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=500_000))
    code, out = run(monkeypatch, spawn(path, session=session))
    assert code == 0
    assert json.loads(out)["systemMessage"]
    sticky = tmp_path / "wish" / "notify-context-size"
    assert sticky.is_dir()
    made = [p for p in tmp_path.rglob("*") if p.is_file() and p.name != "session.jsonl"]
    assert made and all(sticky in p.parents for p in made)


def test_a_session_id_that_is_only_dots_makes_no_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=500_000))
    for session in ("..", "a/.."):
        code, out = run(monkeypatch, spawn(path, session=session))
        assert code == 0
        assert json.loads(out)["systemMessage"]
    assert not (tmp_path / "wish").exists()


def test_the_sticky_directory_is_the_one_scratch_names(tmp_path, monkeypatch):
    """The hook cannot import `tools.registry.scratch` (the system interpreter has no
    repository on its path), so nothing else keeps the two spellings equal."""
    from tools.registry import scratch
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    mod = _module()
    ours = pathlib.Path(mod.sticky_path({"session_id": "abc"}))
    assert ours == scratch.scratch_dir("notify-context-size", "abc")


def test_the_hook_is_registered_on_the_agent_tool():
    """An unregistered hook watches nothing."""
    root = pathlib.Path(__file__).resolve().parents[2]
    claude = json.loads((root / ".claude" / "settings.json").read_text())
    groups = [g for g in claude["hooks"].get("PreToolUse", [])
              if any("notify-context-size.py" in h["command"] for h in g["hooks"])]
    assert groups, "not wired into .claude/settings.json"
    assert "Agent" in groups[0]["matcher"]
    assert "SendMessage" in groups[0]["matcher"]


@pytest.mark.skipif(WINDOWS, reason="/usr/bin/python3 does not exist on Windows")
def test_the_hook_runs_under_the_system_interpreter(tmp_path):
    """The harness runs it, not `.venv`, so it must be standard library only."""
    path = transcript(tmp_path, _turn("assistant", cache_read_input_tokens=500_000))
    done = subprocess.run(
        ["/usr/bin/python3", str(HOOK)], input=json.dumps(spawn(path)),
        capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    assert json.loads(done.stdout)["systemMessage"]
