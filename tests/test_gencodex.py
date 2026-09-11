"""`tools/gencodex.py`: every Codex subagent stays in step with its Claude one.

`#506 (Set Codex up as a second orchestrator with its own subagents, without a
second copy of the rules)`, step 4: `.codex/agents/<name>.toml` is generated
from `.claude/agents/<name>.md`, the way `ui_*.py` is generated from a `.ui`
file. These tests are the `tests/test_generated.py` shape applied to the new
pair.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from tools import gencodex

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_AGENTS = ROOT / ".claude" / "agents"
CODEX_AGENTS = ROOT / ".codex" / "agents"

VALID_EFFORTS = {"low", "medium", "high", "max"}
VALID_MODELS = {"gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}


def test_generated_codex_agents_are_current():
    """Fail if a `.claude/agents/*.md` was changed but gencodex.py wasn't run."""
    result = subprocess.run([sys.executable, "tools/gencodex.py", "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        f"Generated Codex agents are out of date: {result.stdout}\n"
        "Run tools/gencodex.py to update them.")


def test_every_claude_agent_has_a_codex_counterpart_and_no_others_exist():
    """One `.toml` per `.claude/agents/*.md`, and none left over.

    `general-purpose` is a built-in on both sides and has no
    `.claude/agents/general-purpose.md` to generate from, so it correctly has
    no `.codex/agents/general-purpose.toml` either -- this test would catch
    one appearing from hand-editing just as it would catch one going missing.
    """
    want = {md.stem for md in CLAUDE_AGENTS.glob("*.md")}
    have = {toml.stem for toml in CODEX_AGENTS.glob("*.toml")}
    assert have == want


def test_every_generated_toml_parses_and_carries_its_source_body():
    """Each TOML parses, and its `developer_instructions` is byte-identical
    to the Markdown body it came from -- not a paraphrase, not truncated by a
    quoting bug in the backticks, apostrophes or `#` that prose like this
    carries."""
    for md in sorted(CLAUDE_AGENTS.glob("*.md")):
        toml_path = CODEX_AGENTS / f"{md.stem}.toml"
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        text = md.read_text(encoding="utf-8")
        assert data["developer_instructions"] == gencodex.body_of(text), (
            f"{toml_path.name}'s developer_instructions has drifted from "
            f"{md.name}'s body")


def test_every_model_and_effort_is_one_of_the_named_values():
    """`model` is one of Donald's four Codex identifiers; `model_reasoning_effort`
    is one of low/medium/high/max -- never `ultra`, which #506 reserves because
    every one of these agents is itself a subagent."""
    for toml_path in sorted(CODEX_AGENTS.glob("*.toml")):
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        assert data["model"] in VALID_MODELS, (
            f"{toml_path.name} names an unrecognised model {data['model']!r}")
        assert data["model_reasoning_effort"] in VALID_EFFORTS, (
            f"{toml_path.name} names an unrecognised effort "
            f"{data['model_reasoning_effort']!r}")
        assert data["model_reasoning_effort"] != "ultra"


def test_sandbox_mode_matches_the_named_table():
    """`sandbox_mode` comes from `gencodex.READ_ONLY_AGENTS`, a named table,
    not from an agent's Claude `tools:` line.

    A first version inferred it from whether `Write`/`Edit` appeared in
    `tools:`, and it was wrong: `architect` has neither, but has `Bash`, and
    a `Bash` call writes files as freely as `Write` does -- it wrote a 27 KB
    report the same night this was found. Donald then ruled that only
    `code-reviewer` is sandboxed, since never writing is the whole point of
    that one and not of any other: every other agent, including
    `docs-reviewer` and `test-runner` which an earlier version of the table
    also restricted, carries no `sandbox_mode` at all.
    """
    for md in sorted(CLAUDE_AGENTS.glob("*.md")):
        toml_path = CODEX_AGENTS / f"{md.stem}.toml"
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        sandbox_mode = data.get("sandbox_mode")

        if md.stem in gencodex.READ_ONLY_AGENTS:
            assert sandbox_mode == "read-only", (
                f"{md.name} is named in READ_ONLY_AGENTS, so "
                f"{toml_path.name} should be sandbox_mode = \"read-only\" -- "
                f"found {sandbox_mode!r}")
        else:
            assert sandbox_mode is None, (
                f"{md.name} is not named in READ_ONLY_AGENTS, so "
                f"{toml_path.name} should carry no sandbox_mode -- found "
                f"{sandbox_mode!r}")

    assert set(gencodex.READ_ONLY_AGENTS) == {"code-reviewer"}, (
        "Donald's ruling, 2026-09-10, was that only code-reviewer is "
        "sandboxed -- if this is failing because the table grew, that is a "
        "deliberate decision this test should be updated to reflect, not an "
        "assumption to code around")


def test_check_mode_fails_when_a_toml_is_stale(tmp_path):
    """`--check` must actually notice a hand-edited TOML, not just re-run
    clean. Proven by making one wrong and watching it turn red.

    Built as a copy of just the two directories `gencodex.py` reads, under
    `tmp_path`, rather than mutated in place -- the suite runs its test files
    in parallel (`pyproject.toml`'s `addopts`), and the real `.codex/agents/`
    is read by the other tests in this module at the same time.
    """
    import shutil

    shutil.copytree(CLAUDE_AGENTS, tmp_path / ".claude" / "agents")
    shutil.copytree(CODEX_AGENTS, tmp_path / ".codex" / "agents")
    (tmp_path / "tools").mkdir()
    shutil.copy(ROOT / "tools" / "gencodex.py", tmp_path / "tools" / "gencodex.py")

    script = tmp_path / "tools" / "gencodex.py"
    target = tmp_path / ".codex" / "agents" / "junior-dev.toml"

    result = subprocess.run([sys.executable, str(script), "--check"],
                            capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, (
        "the fresh copy should already be clean before it is made stale: "
        f"{result.stdout}{result.stderr}")

    original = target.read_text(encoding="utf-8")
    edited = original.replace('model_reasoning_effort = "medium"',
                              'model_reasoning_effort = "low"')
    assert edited != original, (
        "the replacement did not change anything -- the fixture string no "
        "longer matches junior-dev.toml")
    target.write_text(edited, encoding="utf-8")

    result = subprocess.run([sys.executable, str(script), "--check"],
                            capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode != 0
    assert "junior-dev.toml is stale" in result.stderr
