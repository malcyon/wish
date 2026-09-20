#!/usr/bin/env python3
"""Generate .codex/agents/*.toml from .claude/agents/*.md.

    tools/generate/gencodex.py [--check]

Codex reads a subagent from `.codex/agents/<name>.toml`; Claude Code reads the
same agent from `.claude/agents/<name>.md`. This tool keeps the two from
drifting apart the way `genui.py` keeps a `.ui` and its compiled `ui_*.py`
from drifting apart: the Markdown is the source, the TOML is generated, and
`--check` fails when the generated file does not match what is committed.

The `model` and `model_reasoning_effort` in the TOML are **not** copied from
the Markdown frontmatter -- that frontmatter's `model` field names a Claude
model (`sonnet`, `opus`, `fable`, `haiku`), which is not the model this tool
must write. The Codex identifier and reasoning effort for each agent are
configured in `CODEX_MODELS` below rather than derived. Historical mappings
came from `#506 (Set Codex up as a second orchestrator with its own subagents,
without a second copy of the rules)`'s "Step 4 settled with Donald" comment;
later configured defaults use the same table.

`general-purpose` has no `.claude/agents/general-purpose.md` -- it is a
built-in on both sides -- so it has no row here and gets no TOML.

`sandbox_mode` is a named table (`READ_ONLY_AGENTS` below), not derived from
the Markdown frontmatter's `tools:` line. A first version inferred it from
the absence of `Write`/`Edit` in that line, and it was wrong: `architect`
has neither, but has `Bash`, and a `Bash` call can write a file with a
heredoc, a redirect, `tee` or `cp` as easily as `Write` can -- it wrote a
27 KB report the same night this was found. Every one of the four agents
that line would have restricted has `Bash`, so "no `Write`/`Edit`" proves
nothing about whether an agent can write; only what the agent is *for* does.

Donald's ruling, 2026-09-10: **only `code-reviewer` is sandboxed.** It is the
one agent here whose whole point is never writing -- it reports, and the main
window decides and applies. `docs-reviewer` was in an earlier version of this
table and came out: "the docs reviewer also needs to be able to update
documentation," so its Claude side gained `Write`/`Edit` in the same change
(`.claude/agents/docs-reviewer.md`) and it runs unrestricted here to match.

An agent not in `READ_ONLY_AGENTS` gets no `sandbox_mode` at all and inherits
its parent settings. The omission is not an independent permission grant.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

CLAUDE_AGENTS_DIR = ROOT / ".claude" / "agents"
CODEX_AGENTS_DIR = ROOT / ".codex" / "agents"

#: Codex model identifier and reasoning effort for each agent. Not derived from
#: the Markdown frontmatter's `model` field, which names a Claude model instead.
#: `general-purpose` is deliberately absent: it has no `.claude/agents/` file
#: to generate from, so it gets no TOML either.
CODEX_MODELS = {
    "deep-research": ("gpt-6-astra", "max"),
    "architect": ("gpt-6-astra", "high"),
    "reverse-engineering": ("gpt-5.6-sol", "high"),
    "code-reviewer": ("gpt-5.6-terra", "high"),
    "junior-dev": ("gpt-5.6-terra", "medium"),
    "docs-reviewer": ("gpt-5.6-terra", "medium"),
    "backlog-auditor": ("gpt-5.6-terra", "medium"),
    "changelog-writer": ("gpt-5.6-terra", "medium"),
    "test-runner": ("gpt-5.6-luna", "low"),
    "qt-ui-specialist": ("gpt-5.6-terra", "high"),
    "emulator-runner": ("gpt-5.6-terra", "medium"),
    "senior-analyst": ("gpt-5.6-sol", "high"),
}

#: `model_reasoning_effort` never names this level: every one of these agents
#: is itself a subagent, and `ultra` is where Codex starts delegating on its
#: own initiative rather than when asked -- nesting orchestration inside
#: orchestration is not wanted here. Enforced below, not just documented: a
#: `CODEX_MODELS` entry naming it fails at import time rather than passing
#: silently into a generated TOML.
UNUSED_EFFORT = "ultra"

assert all(effort != UNUSED_EFFORT for _, effort in CODEX_MODELS.values()), (
    f"a CODEX_MODELS entry names {UNUSED_EFFORT!r}, which #506 reserves "
    "because every agent here is itself a subagent")

#: Agents that get `sandbox_mode = "read-only"`, and why -- one line each,
#: decided on what the agent is *for*, never on its `tools:` line. A wrong
#: entry here has to be written by somebody; it cannot arrive silently the
#: way inferring it from `tools:` let `architect` arrive wrong.
#:
#: Donald's ruling, 2026-09-10: only this one. `docs-reviewer` and
#: `test-runner` were here in an earlier version and are not any more --
#: `docs-reviewer` because Donald wants it able to fix what it finds, and
#: `test-runner` was never asked for by name, only carried along by the same
#: mechanical reasoning that put `docs-reviewer` here wrongly.
#:
#: UNKNOWN, and left open rather than guessed at: whether Codex's `read-only`
#: sandbox lets a command reach the network at all. The sandboxing docs say
#: `workspace-write` "asks before using the internet" and say nothing about
#: `read-only`'s network behaviour. `code-reviewer` needs no network today,
#: which is what makes this safe to leave unsettled. Settled by spawning a
#: read-only agent and having it fetch a URL: does it return, stall on an
#: approval nobody can answer, or error outright.
READ_ONLY_AGENTS = {
    "code-reviewer": "reports findings; the main window decides and applies "
                      "them, so the reviewer itself never writes",
}

def _toml_string(value: str) -> str:
    """A TOML basic (double-quoted) string for a single-line value."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def parse_frontmatter(text: str) -> dict[str, str]:
    """The `key: value` pairs from a `.claude/agents/*.md`'s YAML frontmatter.

    Every field in these source files is a single physical line -- confirmed by
    inspection rather than assumed, since a folded YAML value would silently
    break the naive split below.
    """
    _, frontmatter, _ = text.split("---\n", 2)
    fields = {}
    for line in frontmatter.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def body_of(text: str) -> str:
    """The Markdown body: everything after the frontmatter's closing `---`.

    The file has exactly one blank line between the closing `---` and the
    body's first real line, in every source (confirmed, not assumed) --
    that is the single leading `\\n` stripped here, and nothing else about
    the body is touched.
    """
    _, _, rest = text.split("---\n", 2)
    return rest[1:] if rest.startswith("\n") else rest


def codex_body_of(text: str, source: pathlib.Path) -> str:
    """The source body selected for Codex's developer instructions.

    Most agent definitions are shared verbatim. A definition with runtime
    instructions puts its terminal Claude Code block before a terminal Codex
    block. Codex keeps the shared prefix and its own block, byte for byte.
    """
    body = body_of(text)
    claude_marker = "## Claude Code"
    codex_marker = "## Codex"
    claude_headings = list(re.finditer(r"^## Claude Code(?:\n|$)", body,
                                       re.MULTILINE))
    codex_headings = list(re.finditer(r"^## Codex(?:\n|$)", body,
                                      re.MULTILINE))
    claude_count = len(claude_headings)
    codex_count = len(codex_headings)

    if not claude_count and not codex_count:
        return body
    if claude_count != 1 or codex_count != 1:
        raise ValueError(
            f"{source.name} must have exactly one {claude_marker.strip()!r} "
            f"and one {codex_marker.strip()!r} heading")

    claude_start = claude_headings[0].start()
    codex_start = codex_headings[0].start()
    if codex_start < claude_start:
        raise ValueError(
            f"{source.name} must put {claude_marker.strip()!r} before "
            f"{codex_marker.strip()!r}")
    return body[:claude_start] + body[codex_start:]


def sandbox_mode_for(name: str) -> str | None:
    """`"read-only"` for a name in `READ_ONLY_AGENTS`, `None` otherwise.

    Never derived from `tools:` -- `can_write()` used to infer this from
    whether `Write`/`Edit` appeared there, and `architect` proved that wrong:
    it has neither, but has `Bash`, and a `Bash` call writes files as freely
    as `Write` does. `None` leaves `sandbox_mode` unset, which is correct
    for every other agent, which inherits its parent sandbox settings.
    """
    return "read-only" if name in READ_ONLY_AGENTS else None


def toml_for(md_path: pathlib.Path) -> str:
    """The generated TOML source for one `.claude/agents/<name>.md`."""
    text = md_path.read_text(encoding="utf-8")
    fields = parse_frontmatter(text)
    name = fields["name"]
    description = fields["description"]
    body = codex_body_of(text, md_path)
    try:
        model, effort = CODEX_MODELS[name]
    except KeyError:
        raise ValueError(
            f"{md_path.name} has no entry in tools/generate/gencodex.py's CODEX_MODELS "
            "-- Donald has to pick a Codex model and reasoning effort for "
            "any newly added agent before this tool can generate its TOML"
        ) from None
    sandbox_mode = sandbox_mode_for(name)
    sandbox_line = (f"sandbox_mode = {_toml_string(sandbox_mode)}\n"
                    if sandbox_mode is not None else "")
    return (
        f"name = {_toml_string(name)}\n"
        f"description = {_toml_string(description)}\n"
        f"model = {_toml_string(model)}\n"
        f"model_reasoning_effort = {_toml_string(effort)}\n"
        f"{sandbox_line}"
        f"developer_instructions = '''\n{body}'''\n"
    )


def _toml_for_name(name: str) -> pathlib.Path:
    return CODEX_AGENTS_DIR / f"{name}.toml"


def discover() -> list[tuple[pathlib.Path, pathlib.Path]]:
    """Every (.md, .toml) pair this tool generates, in a stable order."""
    return [
        (md, _toml_for_name(md.stem))
        for md in sorted(CLAUDE_AGENTS_DIR.glob("*.md"))
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="fail if a generated .toml differs from its "
                         ".claude/agents/*.md source, or is missing, "
                         "instead of writing it, which is what CI wants")
    args = ap.parse_args(argv)

    pairs = discover()
    if not pairs:
        print("no .claude/agents/*.md files found", file=sys.stderr)
        return 1

    failed = False
    for md, toml in pairs:
        try:
            generated = toml_for(md)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            failed = True
            continue
        if args.check:
            if not toml.exists() or toml.read_text(encoding="utf-8") != generated:
                print(f"{toml.name} is stale; run tools/generate/gencodex.py",
                      file=sys.stderr)
                failed = True
            else:
                print(f"{toml.name} is up to date")
        else:
            CODEX_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
            toml.write_text(generated, encoding="utf-8")
            print(f"{md.name} -> {toml.name}")

    if args.check:
        known = {toml for _, toml in pairs}
        for stray in sorted(CODEX_AGENTS_DIR.glob("*.toml")) if CODEX_AGENTS_DIR.is_dir() else []:
            if stray not in known:
                print(f"{stray.name} has no .claude/agents/*.md source",
                      file=sys.stderr)
                failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
