"""`tools/*.py`: `--help` must never claim a slot, open a window or write a
file.

`#403 (A tool with no argument parser reads --help as input and boots an
emulator)`: `tools/ssbrun.py --help` claimed a pooled VICE instance and
booted it, because the tool scanned `sys.argv` by hand and silently ignored
any token it did not recognise -- so `--help` fell through to the tool's
normal job. `tools/curserun.py` and `tools/session.py` shared the identical
manual-scan shape, and `tools/session.py`'s is worse: with no `--pool` it
drives the *legacy* session on Donald's own 6502/6510/6600, so its
`--help` used to reach for his own machine rather than a pooled one.
`tools/genui.py` and `tools/genlicenses.py` shared a smaller version of the
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

`tests/test_toolshadowing.py` is the pattern this follows: walk every file in
`tools/` rather than a typed list, so the next tool anybody adds is covered,
and name the exceptions individually with the reason each is safe.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "tools"

#: Every script in `tools/`, by module name -- computed at collection, the
#: same way `tests/test_toolshadowing.py`'s `TOOLS` is, so a script added
#: tomorrow is covered without anybody remembering to list it.
TOOLS = tuple(sorted(p.stem for p in TOOLS_DIR.glob("*.py")
                     if p.stem != "__init__"))

#: The last dotted component of a call this project treats as dangerous
#: enough that `--help` must never reach it unguarded: claiming an
#: instance-pool slot, constructing a driven session, booting, launching or
#: serving one, or opening a Qt application.
DANGEROUS_NAMES = frozenset({
    "claim", "claim_slot", "boot", "launch", "serve",
    "Session", "QApplication", "QGuiApplication", "QCoreApplication",
})

#: Tools that reference `sys.argv`/`argv`, or hand-roll their own option
#: recognition, without an `argparse.ArgumentParser` -- checked individually
#: and exempted with the reason `--help` (or any other stray token) cannot
#: reach anything this file calls dangerous.
EXEMPT: dict[str, str] = {
    "d6502": "checks `sys.argv[1] in ('-h', '--help')` itself and exits "
             "before doing anything; a wrong argument count is also caught "
             "and refused",
    "drive": "matches only the literal subcommands 'screen' and "
             "'clear-checkpoints'; anything else, `--help` included, falls "
             "through to printing the module's own docstring",
    "genitems": "an unrecognised argument is read as the disk path and "
                "`goldbox.d64.D64.open` raises `FileNotFoundError` before "
                "the generated doc is written",
    "genspells": "same shape as genitems: the disk is opened before "
                 "anything is written, and a bad path raises first",
    "gentemplates": "same shape as genitems",
    "genmaps": "an unrecognised argument is read as the disks directory; "
               "`glob.glob` on it finds nothing, so the tool prints an "
               "error and exits before writing its doc",
    "loadfiles": "an unrecognised argument is looked up as a game filename "
                 "on the disks; nothing is ever named that, so it prints "
                 "'Not on any side' and writes nothing",
    "unexepack": "requires exactly two positional arguments; `--help` alone "
                 "fails that count and prints usage before either file is "
                 "opened",
    "wallsmap": "treats every argument as a file to read; a nonexistent one "
                "raises before anything is written",
    "wish": "no `__main__` block -- `wish/__main__.py` dispatches on the "
            "first argument instead (docs/129-one-binary.md), so there is "
            "no way to hand this file `--help` directly",
}


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


@pytest.mark.parametrize("name", TOOLS)
def test_help_cannot_reach_a_dangerous_call_unguarded(name):
    if name in EXEMPT:
        pytest.skip(EXEMPT[name])

    tree = ast.parse((TOOLS_DIR / f"{name}.py").read_text(encoding="utf-8"),
                     filename=f"{name}.py")
    block = _main_block(tree)
    if block is None:
        pytest.skip(f"tools/{name}.py has no `if __name__ == '__main__':`, "
                    f"so there is no way to run it directly")

    candidates = _entry_candidates(tree, block)
    dangerous = [d for c in candidates for d in _dangerous_calls(c)]
    argv_aware = any(_references_argv(c) or _has_call_named(c, "ArgumentParser")
                     for c in candidates)

    if not dangerous:
        return  # nothing here that --help could reach unguarded

    assert argv_aware, (
        f"tools/{name}.py calls {dangerous} without ever looking at "
        f"sys.argv or building an argparse parser, so --help runs it "
        f"exactly like any other invocation")

    parses = any(_has_call_named(c, "parse_args") for c in candidates)
    parses_loosely = any(_has_call_named(c, "parse_known_args")
                         for c in candidates)
    assert parses and not parses_loosely, (
        f"tools/{name}.py calls {dangerous} but does not refuse an "
        f"unrecognised argument with argparse's own parse_args -- --help or "
        f"a typo would reach it")


def test_the_family_named_in_403_is_covered():
    """The three tools `#403 (A tool with no argument parser reads --help as
    input and boots an emulator)` names by finding, plus the two it names by
    family, are exactly the ones this file is about -- so a future edit that
    reintroduces a manual scan on one of them fails here by name, not only
    by the general sweep above."""
    for name in ("ssbrun", "curserun", "session", "genui", "genlicenses"):
        assert name in TOOLS, name
        assert name not in EXEMPT, name


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
    from tools import genui

    def _boom(*_a, **_k):
        raise AssertionError("tools/genui.py --help reached compile_ui")

    monkeypatch.setattr(genui, "compile_ui", _boom)
    with pytest.raises(SystemExit) as exc:
        genui.main(["--help"])
    assert exc.value.code == 0


def test_genui_rejects_an_unrecognised_argument_without_writing(monkeypatch):
    from tools import genui

    def _boom(*_a, **_k):
        raise AssertionError("tools/genui.py --bogus reached compile_ui")

    monkeypatch.setattr(genui, "compile_ui", _boom)
    with pytest.raises(SystemExit) as exc:
        genui.main(["--bogus"])
    assert exc.value.code == 2


def test_genlicenses_help_exits_before_writing(monkeypatch):
    from tools import genlicenses

    def _boom(*_a, **_k):
        raise AssertionError("tools/genlicenses.py --help wrote a file")

    monkeypatch.setattr(genlicenses.pathlib.Path, "write_text", _boom)
    with pytest.raises(SystemExit) as exc:
        genlicenses.main(["--help"])
    assert exc.value.code == 0


def test_genlicenses_rejects_an_unrecognised_argument_without_writing(
        monkeypatch):
    from tools import genlicenses

    def _boom(*_a, **_k):
        raise AssertionError("tools/genlicenses.py --bogus wrote a file")

    monkeypatch.setattr(genlicenses.pathlib.Path, "write_text", _boom)
    with pytest.raises(SystemExit) as exc:
        genlicenses.main(["--bogus"])
    assert exc.value.code == 2
