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
