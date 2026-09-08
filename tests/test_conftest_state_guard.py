"""Proof that `tests/conftest.py`'s `_guard_automap_state_data_dir` fires.

`#428 (Ten automapper note tests fail under parallel load but pass alone, so
a green suite depends on how busy the machine is)`: `tools/livecheck.py`
rebound `automap.state._data_dir` at import time, so `tests/test_livecheck.py`
importing it at *its* module level carried the rebinding into every
`pytest -n auto` worker before a single test ran, and every note test
collected afterwards shared one directory. The guard in `tests/conftest.py`
is meant to make that class of bug loud the first time it happens rather
than three investigations later.

This drives a real, separate `pytest` process against a throwaway file
written *inside* `tests/` and removed again -- the fixture under test lives
in `tests/conftest.py` itself, and calling it as a plain function would only
prove the function runs, not that the real collection-time mechanism (an
import poisoning a worker before its first test) is caught.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def _run_throwaway_test(body: str) -> subprocess.CompletedProcess:
    """Write `body` as a test file beside this one, run it, then remove it.

    Living in `tests/` is what makes the real `tests/conftest.py` govern the
    run, the same way it governs every other file here.
    """
    name = f"test_zzz_conftest_guard_probe_{uuid.uuid4().hex}"
    probe = TESTS_DIR / f"{name}.py"
    probe.write_text(textwrap.dedent(body))
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "-n0", str(probe)],
            cwd=TESTS_DIR, capture_output=True, text=True, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
        for leftover in (TESTS_DIR / "__pycache__").glob(f"{name}*"):
            leftover.unlink(missing_ok=True)


def test_an_import_time_rebind_fails_the_suite_instead_of_poisoning_it():
    """The `#428` shape: a raw module-level assignment, at import time.

    Reproduces the mechanism directly instead of importing
    `tools/livecheck.py`, which is fixed now and would prove nothing about
    the guard.
    """
    result = _run_throwaway_test('''
        from automap import state as mapstate

        # Exactly the #428 shape: assigned at module scope, so it runs at
        # collection time, before any test's fixtures -- and never undone.
        mapstate._data_dir = lambda: "/tmp/poisoned-by-a-throwaway-test"


        def test_body_does_nothing_itself():
            pass
    ''')
    assert result.returncode != 0, result.stdout + result.stderr
    assert "#428" in result.stdout, result.stdout
    assert "automap.state._data_dir" in result.stdout, result.stdout


def test_a_monkeypatched_rebind_is_not_flagged():
    """The one legitimate use restores itself and must not be caught.

    Mirrors how `tests/test_livecheck.py` exercises `redirect_notes()`:
    `monkeypatch.setattr` inside the test body, undone at that fixture's own
    teardown before the guard checks. This is the negative control -- without
    it, a guard that flags every rebind regardless of cleanup would also
    fail this file's own legitimate tests.
    """
    result = _run_throwaway_test('''
        from automap import state as mapstate


        def test_body_monkeypatches_and_cleans_up(monkeypatch):
            monkeypatch.setattr(mapstate, "_data_dir", lambda: "/tmp/scoped")
            assert mapstate._data_dir() == "/tmp/scoped"
    ''')
    assert result.returncode == 0, result.stdout + result.stderr
