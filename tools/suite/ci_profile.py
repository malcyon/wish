"""Record collection and per-file test costs only when explicitly loaded by CI."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest


def pytest_configure(config):
    output = os.environ.get("WISH_CI_PROFILE_DIR")
    if output:
        config.pluginmanager.register(Profile(config, Path(output)), "wish-ci-profile")


class Profile:
    def __init__(self, config, output):
        self.config = config
        self.output = output
        self.started = time.perf_counter()
        self.collection_seconds = 0.0
        self.files = {}
        self.workers = set()

    @pytest.hookimpl(wrapper=True)
    def pytest_collection(self, session):
        started = time.perf_counter()
        try:
            return (yield)
        finally:
            self.collection_seconds += time.perf_counter() - started

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodeready(self, node):
        self.workers.add(node.gateway.id)

    def pytest_runtest_logreport(self, report):
        path = report.nodeid.split("::", 1)[0]
        row = self.files.setdefault(path, {
            "setup_seconds": 0.0, "call_seconds": 0.0, "teardown_seconds": 0.0,
            "reports": 0,
        })
        row[f"{report.when}_seconds"] += report.duration
        row["reports"] += 1

    def pytest_sessionfinish(self, session, exitstatus):
        worker = getattr(self.config, "workerinput", {}).get("workerid", "main")
        data = {
            "schema_version": 1,
            "worker": worker,
            "selected_workers": sorted(self.workers),
            "collected_tests": session.testscollected,
            "collection_seconds": self.collection_seconds,
            "session_seconds": time.perf_counter() - self.started,
            "exit_code": int(exitstatus),
            "files": dict(sorted(self.files.items())),
            "note": "Main includes worker reports; do not add main and worker file costs together.",
        }
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / f"pytest-{worker}.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8",
        )
