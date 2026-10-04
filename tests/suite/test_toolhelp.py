"""Every script under `tools/`: `--help` must never claim a slot, open a window or write a
file.

`#403 (A tool with no argument parser reads --help as input and boots an
emulator)`: `tools/secret_of_the_silver_blades/ssbrun.py --help` claimed a pooled VICE instance and
booted it, because the tool scanned `sys.argv` by hand and silently ignored
any token it did not recognise -- so `--help` fell through to the tool's
normal job. `tools/curse_of_the_azure_bonds/curserun.py` and `tools/c64/session.py` shared the identical
manual-scan form, and `tools/c64/session.py`'s is worse: with no `--pool` it
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
handles `-h`/`--help` and rejects an unrecognised argument entirely on its
own, before a single line of the tool's own code runs, so putting a
dangerous call behind it is sufficient without having to run either path.

`tests/suite/test_toolshadowing.py` is the pattern this follows: walk every file in
`tools/` rather than a typed list, so the next tool anybody adds is covered.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass

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


def _entry_candidates(tree: ast.Module, block: ast.If) -> list[ast.AST]:
    """The `__main__` block, plus every function it calls directly.

    One level is enough for every tool in this project: the entry point
    parses its own arguments and only then calls a second function with the
    already-parsed result -- `run(args)`, never `run(argv)` -- so a dangerous
    call reachable from `--help` is always in one of these two places.
    """
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Preserve the first match in the breadth-first traversal.
            functions.setdefault(node.name, node)
    candidates: list[ast.AST] = [block]
    called = {_dotted(call.func).rsplit(".", 1)[-1] for call in _calls(block)}
    for name in called:
        func = functions.get(name)
        if func is not None:
            candidates.append(func)
    return candidates


@dataclass(frozen=True)
class Analysis:
    """A script's classification and failure text, without its source or AST."""

    runnable: bool
    dangerous: tuple[str, ...]
    reason: str | None

    @property
    def guarded(self) -> bool:
        return bool(self.dangerous) or self.reason is not None


def _analyze_source(source: str, filename: str) -> Analysis:
    tree = ast.parse(source, filename=filename)
    block = _main_block(tree)
    if block is None:
        return Analysis(False, (), None)
    candidates = _entry_candidates(tree, block)
    dangerous = [d for c in candidates for d in _dangerous_calls(c)]
    reason = _reason_for_candidates(candidates, dangerous, filename)
    return Analysis(True, tuple(dangerous), reason)


def _reason_for_candidates(candidates, dangerous, filename) -> str | None:
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
        return (f"{filename} calls {dangerous} but does not reject an "
                f"unrecognised argument with argparse's own parse_args -- "
                f"--help or a typo would reach it")
    return None


def _analyze_file(path: pathlib.Path) -> Analysis:
    """Keep an unreadable or malformed script in its own failing test case."""
    try:
        return _analyze_source(path.read_text(encoding="utf-8"), str(path))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        # Store only text: an exception traceback would retain source and ASTs.
        return Analysis(True, (), f"{path}: {type(exc).__name__}: {exc}")


ANALYSES = {name: _analyze_file(TOOLS_DIR / f"{name}.py") for name in TOOLS}
RUNNABLE = tuple(name for name, result in ANALYSES.items() if result.runnable)
GUARDED = tuple(name for name in RUNNABLE if ANALYSES[name].guarded)


@pytest.mark.parametrize("name", GUARDED)
def test_help_cannot_reach_a_dangerous_call_unguarded(name):
    reason = ANALYSES[name].reason
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
    result = _analyze_source(_UNGUARDED_SOURCE, "synthetic_script.py")
    assert result.dangerous == ("Session",)
    reason = result.reason
    assert reason is not None
    assert "sys.argv" in reason


def test_the_filter_leaves_a_script_with_no_dangerous_call_out():
    result = _analyze_source(_NO_DANGEROUS_CALL_SOURCE, "synthetic_script.py")
    assert result.dangerous == ()
    assert result.reason is None


@pytest.mark.parametrize("content, error", [
    (b"def broken(:", "SyntaxError"),
    (b"\xff", "UnicodeDecodeError"),
    (None, "FileNotFoundError"),
])
def test_an_unreadable_script_fails_its_own_case(tmp_path, monkeypatch, content, error):
    path = tmp_path / "broken.py"
    if content is not None:
        path.write_bytes(content)
    result = _analyze_file(path)
    assert result.runnable and result.guarded
    monkeypatch.setitem(ANALYSES, "broken", result)
    with pytest.raises(AssertionError, match=error):
        test_help_cannot_reach_a_dangerous_call_unguarded("broken")


def test_a_module_without_an_entry_point_is_not_runnable():
    result = _analyze_source("def run():\n    return Session()\n", "library.py")
    assert not result.runnable
    assert not result.guarded


def test_duplicate_function_names_keep_the_first_breadth_first_match():
    source = _UNGUARDED_SOURCE.replace(
        'if __name__ == "__main__":',
        'def run():\n    return 1\n\nif __name__ == "__main__":')
    result = _analyze_source(source, "duplicate.py")
    assert result.dangerous == ("Session",)
    assert result.reason is not None


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
