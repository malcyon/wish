"""Diagnostic-only pytest plugin for `#522`: applies `xdist_group` to both
tests in `tests/test_conftest_state_guard.py` at collection time, without
editing that file, so the marker claim in the issue can be checked by
experiment rather than only by reading `pytest-xdist`'s source.

Load alongside `tools.issue522_probe_watch` to see whether grouping removes
the overlap the watcher otherwise reports. Not meant to ship -- the fix, if
any, belongs in the test file itself.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    for item in items:
        if "test_conftest_state_guard" in item.nodeid:
            item.add_marker(pytest.mark.xdist_group(name="issue522-forced"))


@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session):
    """Diagnostic only: record the nodeids xdist's own hook produced, so the
    marker's effect on scheduling can be checked rather than assumed."""
    logdir = Path(os.environ.get(
        "ISSUE522_LOGDIR", Path(__file__).resolve().parent.parent / "work" / "issue522" / "watch"))
    logdir.mkdir(parents=True, exist_ok=True)
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    with open(logdir / f"nodeids-{worker}.log", "a") as fh:
        for item in session.items:
            fh.write(item.nodeid + "\n")
