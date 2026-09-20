"""`tools/generate/gencodex.py`: every Codex subagent stays in step with its Claude one.

`#506 (Set Codex up as a second orchestrator with its own subagents, without a
second copy of the rules)`, step 4: `.codex/agents/<name>.toml` is generated
from `.claude/agents/<name>.md`, the way `ui_*.py` is generated from a `.ui`
file. These tests are the `tests/generate/test_generated.py` design applied to the new
pair.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from tools.generate import gencodex

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_AGENTS = ROOT / ".claude" / "agents"
CODEX_AGENTS = ROOT / ".codex" / "agents"

VALID_EFFORTS = {"low", "medium", "high", "max"}
VALID_MODELS = {"gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
EXPECTED_AGENTS = {
    "architect",
    "backlog-auditor",
    "changelog-writer",
    "code-reviewer",
    "deep-research",
    "docs-reviewer",
    "emulator-runner",
    "junior-dev",
    "qt-ui-specialist",
    "reverse-engineering",
    "senior-analyst",
    "test-runner",
}
EXPECTED_MODELS = {
    "architect": ("gpt-6-astra", "high"),
    "backlog-auditor": ("gpt-5.6-terra", "medium"),
    "changelog-writer": ("gpt-5.6-terra", "medium"),
    "code-reviewer": ("gpt-5.6-terra", "high"),
    "deep-research": ("gpt-6-astra", "max"),
    "docs-reviewer": ("gpt-5.6-terra", "medium"),
    "emulator-runner": ("gpt-5.6-terra", "medium"),
    "junior-dev": ("gpt-5.6-terra", "medium"),
    "qt-ui-specialist": ("gpt-5.6-terra", "high"),
    "reverse-engineering": ("gpt-5.6-sol", "high"),
    "senior-analyst": ("gpt-5.6-sol", "high"),
    "test-runner": ("gpt-5.6-luna", "low"),
}


def test_generated_codex_agents_are_current():
    """Fail if a `.claude/agents/*.md` was changed but gencodex.py wasn't run."""
    result = subprocess.run([sys.executable, "tools/generate/gencodex.py", "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        f"Generated Codex agents are out of date: {result.stdout}\n"
        "Run tools/generate/gencodex.py to update them.")


def test_every_claude_agent_has_a_codex_counterpart_and_no_others_exist():
    """One `.toml` per `.claude/agents/*.md`, and none left over.

    `general-purpose` is a built-in on both sides and has no
    `.claude/agents/general-purpose.md` to generate from, so it correctly has
    no `.codex/agents/general-purpose.toml` either -- this test would catch
    one appearing from hand-editing just as it would catch one going missing.
    """
    want = {md.stem for md in CLAUDE_AGENTS.glob("*.md")}
    have = {toml.stem for toml in CODEX_AGENTS.glob("*.toml")}
    assert want == EXPECTED_AGENTS
    assert have == EXPECTED_AGENTS


def test_every_generated_toml_parses_and_carries_its_selected_source_body():
    """Each TOML parses, and its `developer_instructions` is byte-identical
    to the Markdown body it came from -- not a paraphrase, not truncated by a
    quoting bug in the backticks, apostrophes or `#` that prose like this
    carries."""
    for md in sorted(CLAUDE_AGENTS.glob("*.md")):
        toml_path = CODEX_AGENTS / f"{md.stem}.toml"
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        text = md.read_text(encoding="utf-8")
        fields = gencodex.parse_frontmatter(text)
        assert data["name"] == fields["name"]
        assert data["description"] == fields["description"]
        assert data["developer_instructions"] == gencodex.codex_body_of(text, md), (
            f"{toml_path.name}'s developer_instructions has drifted from "
            f"{md.name}'s selected body")


def test_codex_body_of_keeps_unsplit_and_shared_codex_text_byte_for_byte(tmp_path):
    """Runtime blocks remove only Claude Code instructions from generated TOML."""
    unsplit = "---\nname: test\n---\n\nShared policy.\n"
    split = (
        "---\nname: test\n---\n\nShared policy.\n\n"
        "## Claude Code\n\nClaude-only text.\n\n"
        "## Codex\n\nCodex-only text.\n")
    source = tmp_path / "test.md"
    assert gencodex.codex_body_of(unsplit, source) == gencodex.body_of(unsplit)
    assert gencodex.codex_body_of(split, source) == (
        "Shared policy.\n\n## Codex\n\nCodex-only text.\n")


def test_codex_body_of_rejects_malformed_runtime_headings(tmp_path):
    """A split source has one Claude Code block followed by one Codex block."""
    source = tmp_path / "broken.md"
    bodies = {
        "lone Claude Code": "## Claude Code\n",
        "lone Claude Code at EOF": "## Claude Code",
        "lone Codex": "## Codex\n",
        "lone Codex at EOF": "## Codex",
        "duplicate Claude Code": "## Claude Code\n## Claude Code\n## Codex\n",
        "duplicate Codex": "## Claude Code\n## Codex\n## Codex\n",
        "reversed": "## Codex\n## Claude Code\n",
        "nonterminal Claude Code block": (
            "## Claude Code\n## Codex\n## Claude Code\n"),
        "Claude Code trailing spaces": "## Claude Code  \n## Codex\n",
        "Codex trailing spaces": "## Claude Code\n## Codex \n",
        "both headings trailing spaces": "## Claude Code \n## Codex \n",
        "Claude Code leading space": " ## Claude Code\n## Codex\n",
        "Codex leading spaces": "## Claude Code\n   ## Codex\n",
        "Claude Code tab separator": "##\tClaude Code\n## Codex\n",
        "Codex wide separator": "## Claude Code\n##  Codex\n",
        "both headings indented": " ## Claude Code\n   ## Codex\n",
        "both headings alternate separators": "##\tClaude Code\n##  Codex\n",
        "Claude Code closing markers": "## Claude Code ##\n## Codex\n",
        "Codex closing markers": "## Claude Code\n## Codex ##\n",
        "both headings closing markers": "## Claude Code ##\n## Codex ##\n",
    }
    for label, body in bodies.items():
        text = f"---\nname: test\n---\n\n{body}"
        try:
            gencodex.codex_body_of(text, source)
        except ValueError as exc:
            assert source.name in str(exc), label
        else:
            raise AssertionError(f"{label} did not fail")


def test_split_sources_name_which_runtime_applies_their_section():
    """Claude reads sources directly, so each split profile selects its section."""
    selector = ("Claude Code applies only the `## Claude Code` section below; "
                "Codex applies only the `## Codex` section.")
    for md in sorted(CLAUDE_AGENTS.glob("*.md")):
        body = gencodex.body_of(md.read_text(encoding="utf-8"))
        if "## Claude Code" in body or "## Codex" in body:
            assert selector in body, md.name


def test_generated_runtime_profiles_exclude_claude_only_execution_text():
    """Generated profiles name Codex tools and carry no Claude profile memory."""
    generated = {
        path.stem: tomllib.loads(path.read_text(encoding="utf-8"))["developer_instructions"]
        for path in CODEX_AGENTS.glob("*.toml")
    }
    all_instructions = "\n".join(generated.values())
    assert "\n## Claude Code\n" not in all_instructions
    assert "## Memory" not in all_instructions
    assert "tool call is a turn" not in all_instructions
    assert "`gh issue view N`" not in generated["changelog-writer"]
    assert "tools/github/issueread.py N" in generated["changelog-writer"]
    for name in ("emulator-runner", "test-runner"):
        instructions = generated[name]
        assert "session_id" in instructions
        assert "write_stdin" in instructions
        assert "Monitor" not in instructions
        assert "run_in_background" not in instructions
        assert "task ID" not in instructions
        assert "output-file" not in instructions
        assert "600000" not in instructions
    assert "`Write`" not in generated["code-reviewer"]
    assert "`Edit`" not in generated["code-reviewer"]
    assert "`Write`" not in generated["docs-reviewer"]
    assert "`Edit`" not in generated["docs-reviewer"]


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

    assert gencodex.CODEX_MODELS == EXPECTED_MODELS


def test_generated_profiles_have_only_native_codex_fields():
    """Generated TOML carries Codex's schema, not Claude frontmatter."""
    expected = {
        "name", "description", "model", "model_reasoning_effort",
        "developer_instructions",
    }
    for toml_path in sorted(CODEX_AGENTS.glob("*.toml")):
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        allowed = expected | ({"sandbox_mode"}
                              if toml_path.stem == "code-reviewer" else set())
        assert set(data) == allowed


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
    (tmp_path / "tools" / "generate").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "generate" / "gencodex.py", tmp_path / "tools" / "generate" / "gencodex.py")

    script = tmp_path / "tools" / "generate" / "gencodex.py"
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
