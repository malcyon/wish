"""Check opt-in profiling preserves pytest outcomes and accounts for worker costs."""

import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.suite import ci_measure

REPO = Path(__file__).resolve().parents[2]


def test_auto_workers_preserves_affinity_before_psutil(monkeypatch):
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {2, 4, 6}, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 24)
    assert ci_measure.automatic_workers() == 3


def test_auto_workers_uses_logical_count_without_affinity(monkeypatch):
    monkeypatch.delattr(os, "sched_getaffinity", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert ci_measure.automatic_workers() == 8


def test_samples_keep_exited_cpu_and_do_not_add_successive_rss_samples():
    class Process:
        def __init__(self, pid, rss, cpu):
            self.pid, self.rss, self.cpu = pid, rss, cpu
            self.descendants = []

        def oneshot(self):
            return nullcontext()

        def create_time(self):
            return 1

        def memory_info(self):
            return SimpleNamespace(rss=self.rss)

        def cpu_times(self):
            return SimpleNamespace(user=self.cpu, system=0)

        def children(self, recursive):
            return self.descendants

    parent = Process(1, 10, 2)
    parent.descendants = [Process(2, 20, 3)]
    samples = ci_measure.Samples(SimpleNamespace(Error=RuntimeError), parent)
    samples.take()
    parent.descendants = []
    parent.cpu = 4
    samples.take()
    assert samples.peak_rss == 30
    assert sum(samples.cpu.values()) == 7
    assert samples.peak_processes == 2


@pytest.mark.parametrize("workers", [0, 2])
def test_plugin_preserves_failures_and_complete_file_costs(tmp_path, workers):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_example.py").write_text(
        "def test_pass():\n    assert True\ndef test_fail():\n    assert False\n",
        encoding="utf-8",
    )
    output = tmp_path / "profile"
    env = os.environ.copy()
    env["WISH_CI_PROFILE_DIR"] = str(output)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tools.suite.ci_profile", "-n", str(workers),
         "--dist", "loadgroup", "-q", str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    main = json.loads((output / "pytest-main.json").read_text())
    assert main["collected_tests"] == 2
    assert main["exit_code"] == 1
    assert len(main["selected_workers"]) == workers
    assert sum(row["reports"] for row in main["files"].values()) == 6
    profiles = [json.loads(path.read_text()) for path in output.glob("pytest-gw*.json")]
    if workers:
        assert len(profiles) == workers
        assert all(profile["collected_tests"] == 2 for profile in profiles)
        assert all(profile["collection_seconds"] > 0 for profile in profiles)
    else:
        assert main["collection_seconds"] > 0


def test_wrapper_reports_child_failure_and_keeps_explicit_worker_count(tmp_path, monkeypatch):
    class Child:
        pid = 123
        returncode = 5

        def poll(self):
            return self.returncode

    seen = {}

    def start(command, env):
        seen.update(command=command, env=env)
        return Child()

    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "7")
    monkeypatch.setattr(ci_measure.subprocess, "Popen", start)
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        Process=lambda pid: object(), cpu_count=lambda logical: 4,
    ))
    assert ci_measure.main(["--output", str(tmp_path), "--", "-q"]) == 5
    report = json.loads((tmp_path / "resources.json").read_text())
    assert report["exit_code"] == 5
    assert seen["env"]["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "7"
    assert seen["command"][-1] == "-q"
    assert "--" not in seen["command"]


def test_stop_tree_kills_descendants_that_ignore_termination():
    events = []

    class Process:
        def __init__(self, name):
            self.name = name

        def children(self, recursive):
            return [descendant]

        def terminate(self):
            events.append((self.name, "terminate"))

        def kill(self):
            events.append((self.name, "kill"))

    parent, descendant = Process("parent"), Process("descendant")
    psutil = SimpleNamespace(
        Error=RuntimeError, wait_procs=lambda processes, timeout: ([parent], [descendant]),
    )
    ci_measure.stop_tree(psutil, parent)
    assert events == [("descendant", "terminate"), ("parent", "terminate"),
                      ("descendant", "kill")]
