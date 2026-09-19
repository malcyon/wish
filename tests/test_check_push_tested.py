"""`.claude/hooks/check-push-tested.py` refuses a push until a green suite is recorded for it.

`.claude/rules/commits.md` says the whole suite runs once before every push
that carries code. On 2026-09-16 the orchestrator pushed eighteen times and
launched `test-runner` once, and the batch closing `#89` turned `main` red
on a test neither the builder nor the reviewer had run. The hook is that
sentence's enforcement: `tools/suite/suiterun.py` writes `~/.cache/wish/testrun/<sha>.green`
after a green run, and a push without one stops here rather than on CI.
"""
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

WINDOWS = os.name == "nt"
HOOK = (pathlib.Path(__file__).resolve().parents[1]
        / ".claude" / "hooks" / "check-push-tested.py")


def _module():
    """Load the hook by path -- a hyphenated filename is not importable."""
    spec = importlib.util.spec_from_file_location("_check_push_tested", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t",
                               "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t"})
    return done.stdout.strip()


@pytest.fixture
def clone(tmp_path):
    """A clone with an upstream, one pushed commit, and nothing unpushed."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(remote), str(work))
    (work / "README.md").write_text("start\n")
    git(work, "add", "README.md")
    git(work, "commit", "-q", "-m", "start")
    git(work, "push", "-q", "-u", "origin", "main")
    return work


def commit(work, name, text="x\n"):
    path = work / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(work, "add", name)
    git(work, "commit", "-q", "-m", f"add {name}")
    return git(work, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """A home of its own, so no test reads or writes the real `~/.cache/wish`."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def mark(work, sha):
    d = pathlib.Path(_module().marker_dir())
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sha}.green").write_text("1 passed\n")


def run(monkeypatch, command, cwd, tool="Bash"):
    mod = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": tool, "cwd": str(cwd),
         "tool_input": {"command": command}})))
    return mod.main()


def test_a_push_carrying_code_with_no_marker_is_refused(clone, monkeypatch, capsys):
    sha = commit(clone, "mod.py")
    assert run(monkeypatch, "git push", clone) == 2
    err = capsys.readouterr().err
    assert sha in err
    assert "test-runner" in err


def test_a_marker_for_the_tip_lets_it_through(clone, monkeypatch):
    sha = commit(clone, "mod.py")
    mark(clone, sha)
    assert run(monkeypatch, "git push", clone) == 0


def test_a_documentation_commit_on_top_of_a_tested_one_needs_no_second_run(clone, monkeypatch):
    """A README row or a doc after the run does not need the suite again."""
    tested = commit(clone, "mod.py")
    mark(clone, tested)
    commit(clone, "tools/README.md")
    assert run(monkeypatch, "git push", clone) == 0


def test_a_code_commit_on_top_of_a_tested_one_is_refused(clone, monkeypatch):
    tested = commit(clone, "mod.py")
    mark(clone, tested)
    commit(clone, "tests/test_more.py")
    assert run(monkeypatch, "git push", clone) == 2


def test_a_stale_marker_for_a_commit_that_is_not_an_ancestor_does_not_count(clone, monkeypatch):
    commit(clone, "mod.py")
    mark(clone, "0" * 40)
    assert run(monkeypatch, "git push", clone) == 2


def test_a_documentation_only_push_needs_no_marker(clone, monkeypatch):
    commit(clone, "docs/note.md")
    commit(clone, "CLAUDE.md")
    commit(clone, "tools/README.md")
    assert run(monkeypatch, "git push", clone) == 0


def test_only_prose_markdown_is_documentation(clone, monkeypatch):
    """pyproject.toml, the hook wiring and an agent's source are read by tests."""
    for name in ("pyproject.toml", ".codex/hooks.json",
                 ".codex/agents/junior-dev.toml", ".claude/agents/junior-dev.md"):
        sha = commit(clone, name)
        assert run(monkeypatch, "git push", clone) == 2, name
        mark(clone, sha)


def test_a_commit_and_a_push_in_one_call_are_refused_even_with_a_marker(clone, monkeypatch, capsys):
    """The hook runs before the call, so it would vouch for a HEAD the call replaces."""
    sha = commit(clone, "mod.py")
    mark(clone, sha)
    for command in [
        "git add -A && git commit -m x && git push",
        "git commit -am x; git push",
        "bash -c 'git commit -m x && git push'",
        "git commit -m x\ngit push",
    ]:
        assert run(monkeypatch, command, clone) == 2, command
        assert "one command" in capsys.readouterr().err
    # A push followed by a commit pushes the HEAD the hook saw.
    assert run(monkeypatch, "git push && git commit --allow-empty -m x", clone) == 0


def test_a_ui_file_and_a_test_fixture_both_count_as_code(clone, monkeypatch):
    commit(clone, "ui/window.ui")
    assert run(monkeypatch, "git push", clone) == 2
    mark(clone, git(clone, "rev-parse", "HEAD"))
    commit(clone, "tests/fixtures/thing.bin")
    assert run(monkeypatch, "git push", clone) == 2


def test_the_push_is_seen_however_it_is_reached(clone, monkeypatch):
    commit(clone, "mod.py")
    for command in [
        "git push",
        "git push origin main",
        "cd /tmp && git push",
        "git add x; git commit -m y && git push -u origin main",
        "/usr/bin/git push",
        "bash -c 'git push'",
        "(git push)",
        "git -C /tmp push",
        "git push --force-with-lease",
        "GIT_DIR=x git push",
        "git add -A && git commit -m x && git push;",
        "true;git push",
        "git push&",
        "git push|cat",
        "eval 'git push'",
    ]:
        assert run(monkeypatch, command, clone) == 2, command


def test_commands_that_do_not_push_are_ignored(clone, monkeypatch):
    commit(clone, "mod.py")
    for command in [
        "git status",
        "git log --oneline -5",
        "echo push",
        "grep -n 'git push' docs/x.md",
        "echo 'git push'",
        "git stash push",
        "git tag push",
        "git log push",
        "cat > f.md <<'EOF'\ngit push origin main\nEOF",
    ]:
        assert run(monkeypatch, command, clone) == 0, command


def test_other_tools_are_ignored(clone, monkeypatch):
    commit(clone, "mod.py")
    assert run(monkeypatch, "git push", clone, tool="Read") == 0


def test_outside_a_repository_it_lets_the_push_through(tmp_path, monkeypatch):
    """A tripwire, not a boundary: when git cannot answer, it does not guess."""
    assert run(monkeypatch, "git push", tmp_path) == 0


def test_the_hook_is_registered_on_bash_in_both_harnesses():
    """Claude Code reads `.claude/settings.json`; Codex reads `.codex/hooks.json`."""
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in (root / ".claude" / "settings.json", root / ".codex" / "hooks.json"):
        wiring = json.loads(path.read_text())
        commands = [h["command"]
                    for group in wiring["hooks"].get("PreToolUse", [])
                    if group.get("matcher") == "Bash"
                    for h in group["hooks"]]
        assert any("check-push-tested.py" in c for c in commands), path


def test_the_test_runner_is_told_to_write_the_marker():
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / ".claude" / "agents" / "test-runner.md").read_text()
    assert "testrun/" in text
    assert ".green" in text


def test_the_hook_and_suiterun_read_and_write_one_directory(home):
    """The hook cannot import `tools.registry.scratch`, so it computes the path itself."""
    from tools.registry import scratch
    from tools.suite import suiterun
    assert pathlib.Path(_module().marker_dir()) == scratch.cache_dir("testrun")
    assert suiterun.marker_dir() == scratch.cache_dir("testrun")
    assert scratch.cache_dir("testrun") == home / ".cache" / "wish" / "testrun"


@pytest.mark.skipif(WINDOWS, reason="/usr/bin/python3 does not exist on Windows")
def test_the_hook_runs_under_the_system_interpreter(clone, home):
    """The harness runs it, not `.venv`, so it must be standard library only."""
    sha = commit(clone, "mod.py")
    payload = {"tool_name": "Bash", "cwd": str(clone),
               "tool_input": {"command": "git push"}}
    done = subprocess.run(["/usr/bin/python3", str(HOOK)],
                          input=json.dumps(payload), capture_output=True,
                          env={**os.environ, "HOME": str(home)},
                          text=True, timeout=60)
    assert done.returncode == 2, done.stderr
    assert sha in done.stderr
