#!/usr/bin/env python3
"""Generate .codex/agents/*.toml from .claude/agents/*.md.

    tools/gencodex.py [--check]

Codex reads a subagent from `.codex/agents/<name>.toml`; Claude Code reads the
same agent from `.claude/agents/<name>.md`. This tool keeps the two from
drifting apart the way `genui.py` keeps a `.ui` and its compiled `ui_*.py`
from drifting apart: the Markdown is the source, the TOML is generated, and
`--check` fails when the generated file does not match what is committed.

The `model` and `model_reasoning_effort` in the TOML are **not** copied from
the Markdown frontmatter -- that frontmatter's `model` field names a Claude
model (`sonnet`, `opus`, `fable`, `haiku`), which is not the model this tool
must write. The Codex identifier and reasoning effort for each agent are
Donald's own decision, from `#506 (Set Codex up as a second orchestrator with
its own subagents, without a second copy of the rules)`'s "Step 4 settled
with Donald" comment, and are pinned in `CODEX_MODELS` below rather than
derived.

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

An agent not in `READ_ONLY_AGENTS` gets no `sandbox_mode` at all, because
`workspace-write` is Codex's own documented default for local work
(learn.chatgpt.com/codex/sandboxing: *"workspace-write: ... This is the
default low-friction mode for local work"*) -- naming it would say nothing
`sandbox_mode`'s absence does not already say. `backlog-auditor` is unrestricted
for a separate, still-unsettled reason: see `NO_SANDBOX_RESTRICTION` below.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

CLAUDE_AGENTS_DIR = ROOT / ".claude" / "agents"
CODEX_AGENTS_DIR = ROOT / ".codex" / "agents"

#: Codex model identifier and reasoning effort for each agent, from #506's
#: "Step 4 settled with Donald" comment. Not derived from the Markdown
#: frontmatter's `model` field, which names a Claude model instead.
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

#: Agents left without `sandbox_mode` even though being unable to write
#: might otherwise look like the point.
#:
#: `backlog-auditor` never edits a file, but its whole job is changing issue
#: labels and posting comments through `gh`, which is a network-calling
#: `Bash` invocation rather than a file write. UNKNOWN whether Codex's
#: `read-only` sandbox mode -- documented as "can't edit files or run
#: commands without approval" -- lets that through, blocks it outright, or
#: merely routes it to an approval prompt an unattended subagent cannot
#: answer. Settled by spawning it under `read-only` and watching whether a
#: `gh issue comment` actually posts. Left unrestricted until then.
NO_SANDBOX_RESTRICTION = frozenset({"backlog-auditor"})

assert not (READ_ONLY_AGENTS.keys() & NO_SANDBOX_RESTRICTION), (
    "an agent cannot be both read-only and a named unrestricted exception")


def _toml_string(value: str) -> str:
    """A TOML basic (double-quoted) string for a single-line value."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def parse_frontmatter(text: str) -> dict[str, str]:
    """The `key: value` pairs from a `.claude/agents/*.md`'s YAML frontmatter.

    Every field in these nine files is a single physical line -- confirmed by
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
    body's first real line, in all nine sources (confirmed, not assumed) --
    that is the single leading `\\n` stripped here, and nothing else about
    the body is touched.
    """
    _, _, rest = text.split("---\n", 2)
    return rest[1:] if rest.startswith("\n") else rest


def sandbox_mode_for(name: str) -> str | None:
    """`"read-only"` for a name in `READ_ONLY_AGENTS`, `None` otherwise.

    Never derived from `tools:` -- `can_write()` used to infer this from
    whether `Write`/`Edit` appeared there, and `architect` proved that wrong:
    it has neither, but has `Bash`, and a `Bash` call writes files as freely
    as `Write` does. `None` leaves `sandbox_mode` unset, which is correct
    both for an agent that can write and for `NO_SANDBOX_RESTRICTION`'s
    unsettled exception -- the TOML does not need to tell those two apart.
    """
    return "read-only" if name in READ_ONLY_AGENTS else None


def toml_for(md_path: pathlib.Path) -> str:
    """The generated TOML source for one `.claude/agents/<name>.md`."""
    text = md_path.read_text(encoding="utf-8")
    fields = parse_frontmatter(text)
    name = fields["name"]
    description = fields["description"]
    body = body_of(text)
    try:
        model, effort = CODEX_MODELS[name]
    except KeyError:
        raise ValueError(
            f"{md_path.name} has no entry in tools/gencodex.py's CODEX_MODELS "
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
                print(f"{toml.name} is stale; run tools/gencodex.py",
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
