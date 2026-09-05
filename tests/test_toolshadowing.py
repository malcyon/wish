"""Import order can no longer let `tools/wish.py` shadow the `wish` package.

`#203 (Six test files shadow the wish package with tools/wish.py, which stops
the suite collecting)`: six test files under `tests/` used to put `tools/` on
`sys.path` forever with a bare `sys.path.insert(0, ...)`, so `tools/wish.py`
-- a plain module that happens to share the real `wish` *package*'s name --
won whichever import came first. Once that happened, every later `from wish
import X` in the same process failed with `cannot import name 'X' from
'wish'`, and the suite only worked by the luck of collection order: whichever
test file happened to import the real `wish` before pytest reached one of
the six.

Each check below runs a fresh subprocess that imports one of the six
directly -- no pytest, no `conftest.py` -- and then imports the real `wish`
package straight after, in the same process. That is the sharpest form of
this: it fails regardless of collection order, because there is no second
file for an order to depend on, and it does not lean on `conftest.py` having
already run first the way a real pytest session would.

`#259 (A cold test run intermittently loses the wish package to tools/wish.py,
and a different test fails each time)` is the same fault reached from the
other side: not a *test* file leaving `tools/` on `sys.path`, but a **tool**
doing it -- thirty-four of them do, to reach a sibling by its bare name -- and
then a test importing that tool at collection. Which worker collected which
file decided whether `wish` was already bound, so a cold `__pycache__` failed
a different test each run. The checks over `TOOLS` below are that half, and
they are over every script in `tools/` rather than a list, because the next
tool somebody writes is the one a list would miss.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

SIX = (
    "test_coldread",
    "test_combatdrive",
    "test_savecheck",
    "test_outdoordrive",
    "test_instance",
    "test_genimports",
)


@pytest.mark.parametrize("name", SIX)
def test_importing_one_of_the_six_leaves_wish_importable_afterwards(name):
    """`import <name>` then `import wish` in one fresh process, no pytest."""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO / 'tests')!r})\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        f"import {name}\n"
        "from wish import backends\n"
        "assert backends is not None\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code],
                             cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0 and "OK" in result.stdout, (
        f"import {name}, then import wish, failed:\n{result.stderr}")


@pytest.mark.parametrize("name", SIX)
def test_importing_one_of_the_six_leaves_tools_off_sys_path(name):
    """The assertion above is only sharp for two of the six, so this one.

    Reverted to the pre-fix form, only `test_instance` and `test_genimports`
    actually raise: the other four are saved by an unrelated
    `sys.path.insert(0, repo_root)` in `tools/coldread.py`, `tools/drive.py`
    and `tools/savecheck.py`, which happens to put the real `wish` package
    back in front of `tools/wish.py`. That is luck two layers deep, and it is
    somebody else's file — delete one of those inserts and four of the
    subtests above go on passing while the fault is wide open again.

    So this asserts the property `#203 (Six test files shadow the wish
    package with tools/wish.py, which stops the suite collecting)` actually
    established, which is not incidentally true of any of the six: **after
    importing the module, `tools/` is not left on `sys.path`.** Raised in the
    code review of #183 and #203.
    """
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO / 'tests')!r})\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        f"import {name}\n"
        f"left = [p for p in sys.path if p == {str(REPO / 'tools')!r}]\n"
        "assert not left, f'tools/ left on sys.path: {left}'\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code],
                             cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0 and "OK" in result.stdout, (
        f"import {name} left tools/ on sys.path:\n{result.stderr}")


#: Every script in `tools/`, by module name. Read at collection so a tool
#: added tomorrow is covered without anybody remembering to list it -- which
#: is the whole difference between this and `SIX` above.
TOOLS = tuple(sorted(p.stem for p in (REPO / "tools").glob("*.py")
                     if p.stem != "__init__"))


def _in_a_fresh_process(body: str) -> subprocess.CompletedProcess:
    """Run *body* with the repository root on `sys.path` and nothing else.

    No pytest and no `conftest.py`, so nothing has already imported the real
    `wish` package on the subject's behalf. `QT_QPA_PLATFORM` is inherited
    from `tests/conftest.py`, which forces `offscreen`, so importing a tool
    that reaches Qt opens nothing.
    """
    code = f"import sys\nsys.path.insert(0, {str(REPO)!r})\n{body}"
    return subprocess.run([sys.executable, "-c", code], cwd=REPO,
                          capture_output=True, text=True, timeout=180)


def test_the_tools_package_binds_the_wish_package_before_any_tool_body_runs():
    """`import tools` alone is enough; no individual tool has to behave.

    This is the mechanism behind every `test_importing_a_tool_*` case below.
    Thirty-four scripts in `tools/` put `tools/` at `sys.path[0]` at import
    time and leave it there, so the name `wish` was decided by whichever
    import happened to come first -- `#259 (A cold test run intermittently
    loses the wish package to tools/wish.py, and a different test fails each
    time)`. `tools/__init__.py` runs before any of those bodies and settles
    it.
    """
    result = _in_a_fresh_process(
        "import tools\n"
        "w = sys.modules.get('wish')\n"
        "assert w is not None, 'importing tools did not bind wish at all'\n"
        "assert hasattr(w, '__path__'), f'wish is {w.__file__}'\n"
        "print('OK')\n")
    assert result.returncode == 0 and "OK" in result.stdout, (
        f"`import tools` left the wrong `wish` bound:\n{result.stderr}")


@pytest.mark.parametrize("name", TOOLS)
def test_importing_a_tool_leaves_the_wish_package_reachable(name):
    """`from tools import <tool>`, then `import wish`, in one fresh process.

    Seven tools failed this before `#259 (A cold test run intermittently
    loses the wish package to tools/wish.py, and a different test fails each
    time)` was fixed -- `cursewarp`, `d6502check`, `dosdisk`, `mapmarker`,
    `newecl`, `outdoorsgrep` and `overlay`, each of which put `tools/` in
    front of the repository root and then imported nothing that had already
    pulled the real package in. The other twenty-seven leaking tools passed
    by accident, on something they happened to import first, which is why
    the check is over every tool rather than over the ones that failed.

    The assertion is on `__path__` rather than on any particular attribute:
    a module has none and a package always has one, so it says which of the
    two got the name without depending on what either of them contains.
    """
    result = _in_a_fresh_process(
        f"from tools import {name}\n"
        "import wish\n"
        "assert hasattr(wish, '__path__'), f'wish is {wish.__file__}'\n"
        "print('OK')\n")
    assert result.returncode == 0 and "OK" in result.stdout, (
        f"after `from tools import {name}`, `wish` is not the package:\n"
        f"{result.stderr}")


def test_conftest_binds_the_package_even_with_tools_already_in_front():
    """The pytest half: a worker whose `sys.path` was poisoned before it ran.

    `tests/test_walkrun.py` and half a dozen others put `tools/` on
    `sys.path` by hand and import a script by its bare name, so
    `tools/__init__.py` never runs for them. `tests/conftest.py` is imported
    before any test module in the worker, and this is the property that makes
    that enough: with `tools/` already at index 0 and `wish` unbound,
    importing conftest still leaves the package bound.

    Without the fix this raises the issue's own error --
    `No module named 'wish.ui_window'; 'wish' is not a package` -- from
    `find_spec`, which is used rather than an import so the check costs
    nothing on a machine with no PyQt6.
    """
    result = _in_a_fresh_process(
        f"sys.path.insert(0, {str(REPO / 'tools')!r})\n"
        f"sys.path.insert(0, {str(REPO / 'tests')!r})\n"
        "import conftest  # noqa: F401\n"
        "import wish\n"
        "assert hasattr(wish, '__path__'), f'wish is {wish.__file__}'\n"
        "import importlib.util\n"
        "importlib.util.find_spec('wish.ui_window')\n"
        "print('OK')\n")
    assert result.returncode == 0 and "OK" in result.stdout, (
        f"conftest did not rescue a worker with tools/ at sys.path[0]:\n"
        f"{result.stderr}")


def test_the_tool_that_was_caught_doing_it_no_longer_can():
    """`tools/dosraces.py`, the proven culprit, no longer leaks at all.

    An audit hook on the reproducing batch caught
    `tests/test_dosimport.py`'s own `from wish.ui_window import
    Ui_WishWindow` resolving with `tools/` at `sys.path[0]`, and
    `tools.dosraces` was the only leaking tool loaded in that worker --
    `#259 (A cold test run intermittently loses the wish package to
    tools/wish.py, and a different test fails each time)`.

    This asserts the property `#203 (Six test files shadow the wish package
    with tools/wish.py, which stops the suite collecting)` established, now
    of a *tool*: after importing it, `tools/` is not on `sys.path`. Thirty
    others still leave it there and `tools/pathleak.py` counts them; this one
    is fixed because it is the one that was measured causing the failure.
    """
    result = _in_a_fresh_process(
        "from tools import dosraces  # noqa: F401\n"
        f"left = [p for p in sys.path if p == {str(REPO / 'tools')!r}]\n"
        "assert not left, f'tools/ left on sys.path: {left}'\n"
        "print('OK')\n")
    assert result.returncode == 0 and "OK" in result.stdout, (
        f"tools/dosraces.py left tools/ on sys.path:\n{result.stderr}")
