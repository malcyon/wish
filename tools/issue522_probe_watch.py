"""Diagnostic pytest plugin for `#522 (A conftest guard test fails at random
on the Windows 3.13 job, so a red main no longer means the commit broke
something)`.

Watches `tests/` for the appearance and disappearance of the throwaway probe
files that `tests/test_conftest_state_guard.py`'s `_run_throwaway_test`
writes and removes, without changing that file at all. Loaded with
`-p tools.issue522_probe_watch` on a command line that also runs
`tests/test_conftest_state_guard.py`; every worker `pytest -n auto` starts
gets its own copy of this plugin and its own polling thread, and each writes
its own log file so two workers polling the same directory never interleave
one write.

Not a tool for everyday use -- it exists to answer one question on one issue,
and stays under `tools/` per `.claude/rules/scratch.md` rather than being
thrown away, in case the question needs asking again.

Point it at an output directory with `ISSUE522_LOGDIR`; defaults to
`work/issue522/watch`.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"
PROBE_RE = re.compile(r"^test_zzz_conftest_guard_probe_[0-9a-f]{32}\.py$")
POLL_INTERVAL = 0.001  # 1ms


def _worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


def _log_path() -> Path:
    logdir = Path(os.environ.get("ISSUE522_LOGDIR", TESTS_DIR.parent / "work" / "issue522" / "watch"))
    logdir.mkdir(parents=True, exist_ok=True)
    return logdir / f"{_worker_id()}.log"


class _Watcher:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._log = _log_path()
        self._fh = open(self._log, "a", buffering=1)

    def _write(self, event: str, name: str) -> None:
        self._fh.write(f"{time.time():.6f}\t{_worker_id()}\t{event}\t{name}\n")

    def _run(self) -> None:
        seen: set[str] = set()
        while not self._stop.is_set():
            try:
                current = {
                    p.name for p in TESTS_DIR.iterdir() if PROBE_RE.match(p.name)
                }
            except OSError:
                current = set()
            for name in current - seen:
                self._write("CREATE", name)
            for name in seen - current:
                self._write("DELETE", name)
            seen = current
            time.sleep(POLL_INTERVAL)

    def start(self) -> None:
        self._write("START", "-")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._write("STOP", "-")
        self._fh.close()


_watcher: _Watcher | None = None


def pytest_configure(config) -> None:
    global _watcher
    _watcher = _Watcher()
    _watcher.start()


def pytest_unconfigure(config) -> None:
    if _watcher is not None:
        _watcher.stop()
