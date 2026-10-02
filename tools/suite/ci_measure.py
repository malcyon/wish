"""Run pytest with opt-in timing reports and sampled process-tree resources."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def automatic_workers():
    """Keep xdist's CPU selection from before the profiling dependency is installed."""
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0)) or 1
    return os.cpu_count() or 1


class Samples:
    def __init__(self, psutil, process):
        self.psutil = psutil
        self.process = process
        self.peak_rss = 0
        self.peak_processes = 0
        self.cpu = {}
        self.count = 0
        self.errors = 0

    def take(self):
        rss = 0
        count = 0
        try:
            processes = [self.process, *self.process.children(recursive=True)]
        except self.psutil.Error:
            self.errors += 1
            return
        for process in processes:
            try:
                with process.oneshot():
                    key = (process.pid, process.create_time())
                    rss += process.memory_info().rss
                    cpu = process.cpu_times()
                    self.cpu[key] = max(self.cpu.get(key, 0), cpu.user + cpu.system)
                    count += 1
            except self.psutil.Error:
                self.errors += 1
        self.peak_rss = max(self.peak_rss, rss)
        self.peak_processes = max(self.peak_processes, count)
        self.count += 1


def stop_tree(psutil, process):
    """Stop the child and its descendants when the wrapper is interrupted."""
    try:
        processes = process.children(recursive=True) + [process]
    except psutil.Error:
        return
    for child in processes:
        try:
            child.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=3)
    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    import psutil

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("PYTEST_XDIST_AUTO_NUM_WORKERS", str(automatic_workers()))
    env["WISH_CI_PROFILE_DIR"] = str(output)
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    command = [sys.executable, "-m", "pytest", "-p", "tools.suite.ci_profile",
               "--durations=50", f"--junitxml={output / 'junit.xml'}", *pytest_args]
    started = time.perf_counter()
    interrupted = []

    def interrupt(signum, frame):
        interrupted.append(signum)

    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    child = None
    samples = None
    exit_code = 1
    try:
        child = subprocess.Popen(command, env=env)
        process = psutil.Process(child.pid)
        samples = Samples(psutil, process)
        while child.poll() is None:
            samples.take()
            if interrupted:
                stop_tree(psutil, process)
                child.wait()
                break
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        exit_code = 128 + interrupted[0] if interrupted else child.returncode
    finally:
        if child is not None and child.poll() is None:
            stop_tree(psutil, psutil.Process(child.pid))
            child.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        data = {
            "schema_version": 1,
            "command": command,
            "exit_code": exit_code,
            "wall_seconds": time.perf_counter() - started,
            "logical_cpus": os.cpu_count(),
            "physical_cpus": psutil.cpu_count(logical=False),
            "affinity_cpus": automatic_workers(),
            "automatic_workers": env["PYTEST_XDIST_AUTO_NUM_WORKERS"],
            "sample_interval_seconds": 1,
            "samples": samples.count if samples else 0,
            "sample_errors": samples.errors if samples else 0,
            "peak_sampled_tree_rss_bytes": samples.peak_rss if samples else 0,
            "peak_sampled_processes": samples.peak_processes if samples else 0,
            "sampled_cpu_seconds": sum(samples.cpu.values()) if samples else 0,
            "note": "RSS sums shared pages repeatedly and is not unique RAM. Sampling misses short-lived processes and between-sample peaks; CPU is a sampled lower bound. Wrapper resources are excluded.",
        }
        (output / "resources.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"CI profile: {output}", flush=True)
    return exit_code if exit_code >= 0 else 128 - exit_code


if __name__ == "__main__":
    raise SystemExit(main())
