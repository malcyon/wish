"""Diagnostic pytest plugin for `#522 (A conftest guard test fails at random
on the Windows 3.13 job, so a red main no longer means the commit broke
something)`.

Forces the exact race the issue describes, deterministically, instead of
waiting on `pytest -n auto`'s scheduler to happen to put two probes on disk
at once. `tests/test_conftest_state_guard.py::_run_throwaway_test` runs a
child `pytest` against a single target file; that child, resolving one file
argument, collects the *whole* `tests/` directory first and only afterwards
filters down to the target -- confirmed by instrumenting
`pytest_make_collect_report` directly: a single-file argument against this
tree produces a `Dir` collect report for `tests/` itself, holding all ~280
sibling nodes, before the file the caller actually asked for is picked out
of it. On `win32`, `_pytest/main.py` falls back to `samefile_nofollow()`
for every sibling whose path does not string-equal the target's, and that
function calls `.lstat()` on both arguments with no missing-file handling.

This plugin hooks the same `pytest_make_collect_report` call, waits for the
`tests/` directory's own report, and -- once it holds a node for the
sibling file named by `ISSUE522_SIBLING` -- deletes that file from disk
before returning, in `ISSUE522_MODE=force`. The matching loop in
`_pytest/main.py` then finds a `Node` whose `.path` no longer exists. In
`ISSUE522_MODE=control`, the sibling is left alone, and the same loop
sees every path that it looks at.

It also wraps `samefile_nofollow` itself, in both `_pytest.pathlib` (where
it is defined) and `_pytest.main` (where it was imported by name, so
patching the first module does not reach the second), logging both of its
arguments and any exception before the call proceeds -- so a failure can be
attributed to the actual pair of paths involved rather than assumed.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"

_MODE = os.environ.get("ISSUE522_MODE", "control")
_SIBLING = os.environ.get("ISSUE522_SIBLING", "")
_LOG = Path(os.environ.get("ISSUE522_LOG", "issue522_repro.log"))
_deleted = False


def _log(line: str) -> None:
    with open(_LOG, "a") as fh:
        fh.write(f"{time.time():.6f}\t{line}\n")


def pytest_configure(config) -> None:
    import _pytest.main as m
    import _pytest.pathlib as pl

    original = pl.samefile_nofollow

    def wrapped(p1: Path, p2: Path) -> bool:
        _log(f"samefile_nofollow(p1={p1}, p2={p2})")
        try:
            result = original(p1, p2)
        except Exception as exc:  # noqa: BLE001 -- logging, then re-raising unchanged
            _log(f"samefile_nofollow RAISED {type(exc).__name__}: {exc}")
            raise
        _log(f"samefile_nofollow -> {result}")
        return result

    pl.samefile_nofollow = wrapped
    m.samefile_nofollow = wrapped  # `from _pytest.pathlib import samefile_nofollow`


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    global _deleted
    if _deleted or _MODE != "force" or not _SIBLING:
        return
    if getattr(collector, "path", None) != TESTS_DIR:
        return
    rep = outcome.get_result()
    if not rep.passed:
        return
    for node in rep.result:
        if getattr(node, "path", None) == TESTS_DIR / _SIBLING:
            _log(f"deleting sibling {node.path} right after its collect report")
            node.path.unlink(missing_ok=True)
            _deleted = True
            return
    _log(f"sibling {_SIBLING} not found among {len(rep.result)} subnodes")
