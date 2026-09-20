"""`.claude/hooks/check-orchestrator-edits.py` refuses the orchestrator's own edits.

`.claude/skills/orchestrate/SKILL.md` says the orchestrator never edits a
file itself -- every change goes to a subagent. This hook makes that
mechanical: a `PreToolUse` hook on `Edit`, `Write`, `MultiEdit` and
`NotebookEdit` that refuses when the call is the main window's (not a
subagent's, which carries an `agent_id` and is handed the main session's
`transcript_path`), the transcript has shown the
orchestrate skill's opening sentence, and the file being written is inside
the repository.
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
        / ".claude" / "hooks" / "check-orchestrator-edits.py")

MARKER_LINE = json.dumps({
    "type": "user",
    "message": {"content": [
        {"type": "text",
         "text": "You are the orchestrator for this session. You never "
                 "run anything yourself."},
    ]},
})
PLAIN_LINE = json.dumps({
    "type": "user",
    "message": {"content": [{"type": "text", "text": "read this file for me"}]},
})


def _module():
    """Load the hook by path -- a hyphenated filename is not importable."""
    spec = importlib.util.spec_from_file_location("_check_orchestrator_edits", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(monkeypatch, payload):
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return mod.main()


def transcript(tmp_path, marker, subdir=""):
    directory = tmp_path / subdir if subdir else tmp_path
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "session.jsonl"
    lines = [MARKER_LINE if marker else PLAIN_LINE]
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def call(transcript_path, file_path, tool="Edit"):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return {
        "tool_name": tool,
        "transcript_path": transcript_path,
        "tool_input": {key: file_path, "old_string": "a", "new_string": "b"},
    }


@pytest.fixture
def isolated_tmp(tmp_path, monkeypatch):
    """A private temp directory, so the hook's stamp files never collide
    with another test or a real session's."""
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return tmp_path


def test_a_subagent_transcript_is_let_through(isolated_tmp, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(isolated_tmp / "repo"))
    path = transcript(isolated_tmp, marker=True, subdir="proj/session/subagents")
    inside = str(isolated_tmp / "repo" / "wish" / "foo.py")
    assert run(monkeypatch, call(path, inside)) == 0


def test_a_subagent_call_with_the_main_transcript_is_let_through(isolated_tmp, monkeypatch):
    """A subagent's call carries the main session's transcript path, so the
    `agent_id` field is what tells it apart."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(isolated_tmp / "repo"))
    path = transcript(isolated_tmp, marker=True)
    inside = str(isolated_tmp / "repo" / "wish" / "foo.py")
    payload = call(path, inside)
    assert run(monkeypatch, payload) == 2
    payload["agent_id"] = "agent-a6f81c9ca893490ad"
    payload["agent_type"] = "junior-dev"
    assert run(monkeypatch, payload) == 0


def test_a_main_window_transcript_without_the_marker_is_let_through(isolated_tmp, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(isolated_tmp / "repo"))
    path = transcript(isolated_tmp, marker=False)
    inside = str(isolated_tmp / "repo" / "wish" / "foo.py")
    assert run(monkeypatch, call(path, inside)) == 0


def test_a_main_window_transcript_with_the_marker_is_refused_for_a_repository_file_and_let_through_outside_it(
        isolated_tmp, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(isolated_tmp / "repo"))
    path = transcript(isolated_tmp, marker=True)
    inside = str(isolated_tmp / "repo" / "wish" / "foo.py")
    outside = str(isolated_tmp / "elsewhere" / "scratch.py")

    assert run(monkeypatch, call(path, inside)) == 2
    err = capsys.readouterr().err
    assert "does not edit files" in err
    assert "junior-dev" in err
    assert inside in err

    assert run(monkeypatch, call(path, outside)) == 0


def test_no_transcript_path_is_let_through(isolated_tmp, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(isolated_tmp / "repo"))
    payload = call(None, str(isolated_tmp / "repo" / "x.py"))
    del payload["transcript_path"]
    assert run(monkeypatch, payload) == 0


def test_the_stamp_makes_the_second_call_skip_re_reading(isolated_tmp, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(isolated_tmp / "repo"))
    path = transcript(isolated_tmp, marker=True)
    inside = str(isolated_tmp / "repo" / "wish" / "foo.py")

    assert run(monkeypatch, call(path, inside)) == 2
    capsys.readouterr()

    os.remove(path)
    assert not os.path.exists(path)
    # The transcript is gone; a fresh read would treat that as "let through"
    # (an unreadable transcript never refuses), so a refusal here proves the
    # stamp answered instead of the file.
    assert run(monkeypatch, call(path, inside)) == 2
    assert "does not edit files" in capsys.readouterr().err


def test_other_tools_are_ignored(isolated_tmp, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(isolated_tmp / "repo"))
    path = transcript(isolated_tmp, marker=True)
    inside = str(isolated_tmp / "repo" / "wish" / "foo.py")
    assert run(monkeypatch, call(path, inside, tool="Bash")) == 0


def test_notebook_edit_is_read_from_its_own_key(isolated_tmp, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(isolated_tmp / "repo"))
    path = transcript(isolated_tmp, marker=True)
    inside = str(isolated_tmp / "repo" / "notebook.ipynb")
    assert run(monkeypatch, call(path, inside, tool="NotebookEdit")) == 2
    assert inside in capsys.readouterr().err


def test_a_malformed_payload_is_let_through(isolated_tmp, monkeypatch):
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert mod.main() == 0


def test_the_git_root_is_used_when_claude_project_dir_is_unset(isolated_tmp, monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    repo = isolated_tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    path = transcript(isolated_tmp, marker=True)
    inside = str(repo / "wish" / "foo.py")

    payload = call(path, inside)
    payload["cwd"] = str(repo)
    assert run(monkeypatch, payload) == 2

    outside = str(isolated_tmp / "elsewhere" / "scratch.py")
    payload = call(path, outside)
    payload["cwd"] = str(repo)
    assert run(monkeypatch, payload) == 0


def test_the_hook_is_registered_on_the_edit_tools():
    root = pathlib.Path(__file__).resolve().parents[2]
    claude = json.loads((root / ".claude" / "settings.json").read_text())
    groups = [g for g in claude["hooks"].get("PreToolUse", [])
              if any("check-orchestrator-edits.py" in h["command"] for h in g["hooks"])]
    assert groups, "not wired into .claude/settings.json"
    matcher = groups[0]["matcher"]
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        assert tool in matcher


@pytest.mark.skipif(WINDOWS, reason="/usr/bin/python3 does not exist on Windows")
def test_the_hook_runs_under_the_system_interpreter(isolated_tmp):
    """The harness runs it, not `.venv`, so it must be standard library only."""
    repo = isolated_tmp / "repo"
    repo.mkdir()
    path = transcript(isolated_tmp, marker=True)
    inside = str(repo / "wish" / "foo.py")
    env = {**os.environ, "TMPDIR": str(isolated_tmp / "tmp"),
           "CLAUDE_PROJECT_DIR": str(repo)}
    done = subprocess.run(
        ["/usr/bin/python3", str(HOOK)], input=json.dumps(call(path, inside)),
        capture_output=True, text=True, timeout=30, env=env)
    assert done.returncode == 2, done.stderr
    assert "does not edit files" in done.stderr
