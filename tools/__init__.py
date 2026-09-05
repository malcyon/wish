"""Developer scripts, as a package -- and the one import that has to happen
before any of them runs.

`tools/wish.py` is a plain module that happens to share the `wish` *package*'s
name, and thirty-four scripts in here put `tools/` at the **front** of
`sys.path` at import time and never take it off, so that a sibling can be
reached as `import dosbox`. Put those two facts in one process and the first
`import wish` after any of them resolves to `tools/wish.py`, which has no
`__path__`; every later `from wish.ui_window import ...` in that process then
fails with `No module named 'wish.ui_window'; 'wish' is not a package`.

Which import comes first decided whether the process was poisoned, and under
`pytest -n auto` that is decided by which worker collected which file, so a
different test failed on each run -- see
`#259 (A cold test run intermittently loses the wish package to tools/wish.py,
and a different test fails each time)`. Binding the real package here, before
any tool body has run, is what makes the order stop mattering: `from tools
import anything` cannot leave a process with the wrong `wish`.

The repository root goes in front for the duration of that one import and is
put straight back, so this works even when a tool earlier in the same process
already left `tools/` at index 0. It is the sibling of this package in a source
checkout and the same site-packages directory in an installed one, so the
`wish` bound here is the one that belongs with these tools either way.
"""
from __future__ import annotations

import pathlib
import sys

_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
_saved = sys.path[:]
sys.path.insert(0, _ROOT)
try:
    import wish  # noqa: F401
except ImportError:          # a build that ships the scripts without the app
    pass
finally:
    sys.path[:] = _saved
del _saved
