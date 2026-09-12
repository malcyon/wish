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

import pytest

# Both tests here write a uniquely-named probe **into `tests/`** and delete it
# again, on the assumption that only one is doing so at a time. Under
# `-n auto` that assumption is false: neither carried a group, so
# `--dist loadgroup` scheduled them on separate workers and their probes
# coexisted on disk for 296-356 ms in 20 of 20 runs measured on 2026-09-12.
#
# That overlap is what `#522` was: a child `pytest` given one file to collect
# still enumerates the whole directory first, and on Windows
# `_pytest/main.py` falls back to `samefile_nofollow` for every sibling whose
# path does not match -- which `lstat()`s a file the *other* test has just
# deleted and raises `WinError 2`. Linux never reaches that branch, which is
# why it only ever failed on the Windows job. One group, 0 of 20 overlaps.
#
# The same reasoning as `tests/test_instance.py`'s `emulator-pool` group: a
# test claiming a shared resource has to land in one worker. The resource
# here is the `tests/` directory during a child's collection.
pytestmark = pytest.mark.xdist_group(name="conftest-guard-probe")

TESTS_DIR = Path(__file__).resolve().parent


def _run_throwaway_test(body: str) -> subprocess.CompletedProcess:
    """Write `body` as a test file beside this one, run it, then remove it.

    The write and the collection that reads it back happen inside the *same*
    process -- the subprocess below, fed `body` on its stdin -- rather than
    this process writing the file and a separately spawned one opening it.
    `#448 (The conftest guard's own probe test fails on Windows CI with the
    probe file not found)` was exactly that handoff: this process wrote the
    probe and closed it, a freshly spawned child immediately tried to collect
    it, and on the Windows runners the two were not reliably ordered, so the
    child's own collection saw `FileNotFoundError` for a file its parent had
    already written -- intermittently, never on Linux, and never in the
    subprocess's own separate `-n auto` workers (there were none: this file's
    `-n0` already overrode the `-n auto` in `pyproject.toml`'s `addopts`,
    confirmed locally before ruling that out). A single process's own write
    is always visible to its own next read; only the cross-process boundary
    was ever in question, and putting the write inside the same process that
    collects removes that boundary rather than racing it.

    Living in `tests/` is what makes the real `tests/conftest.py` govern the
    run, the same way it governs every other file here.
    """
    name = f"test_zzz_conftest_guard_probe_{uuid.uuid4().hex}"
    probe = TESTS_DIR / f"{name}.py"
    runner = textwrap.dedent(f"""
        import sys
        from pathlib import Path

        Path({str(probe)!r}).write_text(sys.stdin.read())
        import pytest
        raise SystemExit(pytest.main(
            ["-q", "-p", "no:cacheprovider", "-n0", {str(probe)!r}]))
    """)
    try:
        return subprocess.run(
            [sys.executable, "-c", runner],
            cwd=TESTS_DIR, input=textwrap.dedent(body),
            capture_output=True, text=True, timeout=90)
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
