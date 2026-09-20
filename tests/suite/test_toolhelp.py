"""Every script under `tools/`: `--help` must never claim a slot, open a window or write a
file.

`#403 (A tool with no argument parser reads --help as input and boots an
emulator)`: `tools/secret_of_the_silver_blades/ssbrun.py --help` claimed a pooled VICE instance and
booted it, because the tool scanned `sys.argv` by hand and silently ignored
any token it did not recognise -- so `--help` fell through to the tool's
normal job. `tools/curse_of_the_azure_bonds/curserun.py` and `tools/c64/session.py` shared the identical
manual-scan shape, and `tools/c64/session.py`'s is worse: with no `--pool` it
drives the *legacy* session on Donald's own 6502/6510/6600, so its
`--help` used to reach for his own machine rather than a pooled one.
`tools/generate/genui.py` and `tools/generate/genlicenses.py` shared a smaller version of the
same fault: anything but the literal string `"--check"` fell through to the
write branch, so `--help` rewrote generated source and a licence file.

Proving this the way `.claude/rules/testing.md` asks -- by actually running
each tool with `--help` -- is the one thing this file must never do: for a
tool that has not been fixed yet, that is exactly the incident happening
again. So this reads each tool's own source with `ast`, which cannot boot
anything, and asks a narrower question than "does `--help` work": **does
every call this project considers dangerous -- claiming a pool slot,
constructing a `Session`, calling `.boot`/`.launch`/`.serve`, or opening a Qt
application -- sit behind a call to `argparse`'s own `parse_args`, in the
same function or in the function that calls it?** `argparse.parse_args`
handles `-h`/`--help` and refuses an unrecognised argument entirely on its
own, before a single line of the tool's own code runs, so putting a
dangerous call behind it is sufficient without having to run either path.

`tests/suite/test_toolshadowing.py` is the pattern this follows: walk every file in
`tools/` rather than a typed list, so the next tool anybody adds is covered.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO / "tools"

#: Every script under `tools/`, by its path below `tools/` without the
#: suffix (`dos/dosbox`) -- computed at collection, the same way
#: `tests/suite/test_toolshadowing.py`'s `TOOLS` is, so a script added tomorrow, in
#: any subdirectory, is covered without anybody remembering to list it.
TOOLS = tuple(sorted(
    p.relative_to(TOOLS_DIR).with_suffix("").as_posix()
    for p in TOOLS_DIR.rglob("*.py") if p.stem != "__init__"))

#: The same scripts by bare name.
STEMS = {name.rsplit("/", 1)[-1]: name for name in TOOLS}

#: The last dotted component of a call this project treats as dangerous
#: enough that `--help` must never reach it unguarded: claiming an
#: instance-pool slot, constructing a driven session, booting, launching or
#: serving one, or opening a Qt application.
DANGEROUS_NAMES = frozenset({
    "claim", "claim_slot", "boot", "launch", "serve",
    "Session", "QApplication", "QGuiApplication", "QCoreApplication",
})


def _dotted(node: ast.expr) -> str:
    """`foo.bar.baz(...)` as `"foo.bar.baz"`, or `""` for anything else."""
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _calls(node: ast.AST):
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            yield child


def _dangerous_calls(node: ast.AST) -> list[str]:
    return [dotted for call in _calls(node)
           if (dotted := _dotted(call.func)).rsplit(".", 1)[-1]
           in DANGEROUS_NAMES]


def _has_call_named(node: ast.AST, suffix: str) -> bool:
    return any(_dotted(call.func).endswith(suffix) for call in _calls(node))


def _references_argv(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr == "argv":
            return True
        if isinstance(child, ast.Name) and child.id == "argv":
            return True
    return False


def _main_block(tree: ast.Module) -> ast.If | None:
    """The top-level `if __name__ == "__main__":`, if the module has one."""
    for node in tree.body:
        if (isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"):
            return node
    return None


def _function_named(tree: ast.Module, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    return None


def _entry_candidates(tree: ast.Module, block: ast.If) -> list[ast.AST]:
    """The `__main__` block, plus every function it calls directly.

    One level is enough for every tool in this project: the entry point
    parses its own arguments and only then calls a second function with the
    already-parsed result -- `run(args)`, never `run(argv)` -- so a dangerous
    call reachable from `--help` is always in one of these two places.
    """
    candidates: list[ast.AST] = [block]
    called = {_dotted(call.func).rsplit(".", 1)[-1] for call in _calls(block)}
    for name in called:
        func = _function_named(tree, name)
        if func is not None:
            candidates.append(func)
    return candidates


def _has_main_block(name: str) -> bool:
    """Does the script have an `if __name__ == "__main__":` block?

    A file that cannot be read or parsed counts as having one, so it stays in
    `RUNNABLE` and fails its own case rather than every case at collection."""
    try:
        tree = ast.parse((TOOLS_DIR / f"{name}.py").read_text(encoding="utf-8"),
                         filename=f"{name}.py")
    except (SyntaxError, UnicodeDecodeError, OSError):
        return True
    return _main_block(tree) is not None


#: The scripts that can be run directly, which is the only kind `--help` can
#: be handed to: the ones with an `if __name__ == "__main__":` block.
RUNNABLE = tuple(name for name in TOOLS if _has_main_block(name))


def _entry_dangerous(source: str, filename: str = "<source>") -> list[str]:
    """The dangerous calls in a script's `__main__` block or in a function that
    block calls directly, or `[]` when it has no `__main__` block."""
    tree = ast.parse(source, filename=filename)
    block = _main_block(tree)
    if block is None:
        return []
    return [d for c in _entry_candidates(tree, block)
            for d in _dangerous_calls(c)]


def _unguarded_reason(source: str, filename: str) -> str | None:
    """Why `--help` could reach a dangerous call in this script unguarded, or
    `None` when it cannot: the call is absent, or argparse's `parse_args`
    is called before it."""
    tree = ast.parse(source, filename=filename)
    block = _main_block(tree)
    assert block is not None, filename

    candidates = _entry_candidates(tree, block)
    dangerous = [d for c in candidates for d in _dangerous_calls(c)]
    if not dangerous:
        return None

    argv_aware = any(_references_argv(c) or _has_call_named(c, "ArgumentParser")
                     for c in candidates)
    if not argv_aware:
        return (f"{filename} calls {dangerous} without ever looking at "
                f"sys.argv or building an argparse parser, so --help runs it "
                f"exactly like any other invocation")

    parses = any(_has_call_named(c, "parse_args") for c in candidates)
    parses_loosely = any(_has_call_named(c, "parse_known_args")
                         for c in candidates)
    if not (parses and not parses_loosely):
        return (f"{filename} calls {dangerous} but does not refuse an "
                f"unrecognised argument with argparse's own parse_args -- "
                f"--help or a typo would reach it")
    return None


def _guarded(name: str) -> bool:
    """Does the script have a dangerous call for `--help` to reach?

    A file that cannot be read or parsed counts as having one, so it stays in
    the sweep and fails its own case rather than every case at collection."""
    try:
        return bool(_entry_dangerous(
            (TOOLS_DIR / f"{name}.py").read_text(encoding="utf-8"),
            f"{name}.py"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return True


#: The runnable scripts that have a dangerous call in their entry point --
#: the only ones the sweep below has anything to say about. Computed from each
#: tool's own source at collection, so a tool that gains a `claim` or a
#: `QApplication` joins the sweep without anybody listing it.
GUARDED = tuple(name for name in RUNNABLE if _guarded(name))


@pytest.mark.parametrize("name", GUARDED)
def test_help_cannot_reach_a_dangerous_call_unguarded(name):
    reason = _unguarded_reason(
        (TOOLS_DIR / f"{name}.py").read_text(encoding="utf-8"),
        f"tools/{name}.py")
    assert reason is None, reason


_UNGUARDED_SOURCE = """
from tools.c64.session import Session

def run():
    return Session()

if __name__ == "__main__":
    run()
"""

_NO_DANGEROUS_CALL_SOURCE = """
def run():
    return 1

if __name__ == "__main__":
    run()
"""


def test_the_filter_classifies_a_session_with_no_parser_as_dangerous():
    assert _entry_dangerous(_UNGUARDED_SOURCE) == ["Session"]
    reason = _unguarded_reason(_UNGUARDED_SOURCE, "synthetic_script.py")
    assert reason is not None
    assert "sys.argv" in reason


def test_the_filter_leaves_a_script_with_no_dangerous_call_out():
    assert _entry_dangerous(_NO_DANGEROUS_CALL_SOURCE) == []
    assert _unguarded_reason(_NO_DANGEROUS_CALL_SOURCE, "synthetic_script.py") is None


def test_the_family_named_in_403_is_covered():
    """The three tools `#403 (A tool with no argument parser reads --help as
    input and boots an emulator)` names by finding, plus the two it names by
    family, are exactly the ones this file is about -- so a future edit that
    reintroduces a manual scan on one of them fails here by name, not only
    by the general sweep above."""
    for name in ("ssbrun", "curserun", "session", "genui", "genlicenses"):
        assert name in STEMS, name
        assert STEMS[name] in RUNNABLE, name
    # The three the sweep exists for must be in it; genui and genlicenses are
    # not, since neither has a dangerous call.
    for name in ("ssbrun", "curserun", "session"):
        assert STEMS[name] in GUARDED, name
    # An empty `parametrize` list collects one skipped test and asserts
    # nothing, so a filter that matches nothing has to fail here instead.
    assert len(RUNNABLE) >= 300
    assert len(GUARDED) >= 50


# ---------------------------------------------------------------------------
# `genui.py` and `genlicenses.py`: the file-writing half of the same fault
# ---------------------------------------------------------------------------
#
# Neither touches the emulator or Qt, so calling `main(["--help"])` directly
# is safe in a way it never is for `ssbrun`, `curserun` or `session` -- there
# is nothing here `.claude/rules/emulator.md` governs. The sweep above only
# asks about `DANGEROUS_NAMES`, which is scoped to the pool and to Qt, so it
# would not have caught either of these: both wrote unconditionally unless
# the literal string `"--check"` was in `argv`, which `--help` never is.
# These two run the real fix instead of reading its source.

def test_genui_help_exits_before_compiling_anything(monkeypatch):
    from tools.generate import genui

    def _boom(*_a, **_k):
        raise AssertionError("tools/generate/genui.py --help reached compile_ui")

    monkeypatch.setattr(genui, "compile_ui", _boom)
    with pytest.raises(SystemExit) as exc:
        genui.main(["--help"])
    assert exc.value.code == 0


def test_genui_rejects_an_unrecognised_argument_without_writing(monkeypatch):
    from tools.generate import genui

    def _boom(*_a, **_k):
        raise AssertionError("tools/generate/genui.py --bogus reached compile_ui")

    monkeypatch.setattr(genui, "compile_ui", _boom)
    with pytest.raises(SystemExit) as exc:
        genui.main(["--bogus"])
    assert exc.value.code == 2


def test_genlicenses_help_exits_before_writing(monkeypatch):
    from tools.generate import genlicenses

    def _boom(*_a, **_k):
        raise AssertionError("tools/generate/genlicenses.py --help wrote a file")

    monkeypatch.setattr(genlicenses.pathlib.Path, "write_text", _boom)
    with pytest.raises(SystemExit) as exc:
        genlicenses.main(["--help"])
    assert exc.value.code == 0


def test_genlicenses_rejects_an_unrecognised_argument_without_writing(
        monkeypatch):
    from tools.generate import genlicenses

    def _boom(*_a, **_k):
        raise AssertionError("tools/generate/genlicenses.py --bogus wrote a file")

    monkeypatch.setattr(genlicenses.pathlib.Path, "write_text", _boom)
    with pytest.raises(SystemExit) as exc:
        genlicenses.main(["--bogus"])
    assert exc.value.code == 2
