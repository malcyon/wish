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
