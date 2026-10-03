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
        processes = [process]
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


def stop_child(psutil, child):
    """Bound cleanup even when process inspection or termination is denied."""
    try:
        stop_tree(psutil, psutil.Process(child.pid))
    except psutil.Error:
        pass
    try:
        child.wait(timeout=3)
        return True
    except subprocess.TimeoutExpired:
        try:
            child.kill()
        except OSError:
            pass
    try:
        child.wait(timeout=3)
        return True
    except subprocess.TimeoutExpired:
        return False


def shard_arguments(parser, args, output):
    """Validate measured weights and compute one plan before starting pytest."""
    supplied = (args.shard_index is not None, args.weights is not None,
                args.weight_key is not None)
    if not any(supplied):
        if args.shard_count != 2:
            parser.error("--shard-count requires shard weights and an index")
        return [], None
    if not all(supplied):
        parser.error("--shard-index, --weights and --weight-key are required together")
    if args.shard_count < 1 or args.shard_index < 0 or args.shard_index >= args.shard_count:
        parser.error("--shard-count must be positive and --shard-index within its range")
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.suite import ci_shard

    try:
        data = json.loads(args.weights.read_text(encoding="utf-8"))
        ci_shard.validate_weights(data)
        platforms = data["platforms"]
        if args.weight_key not in platforms:
            raise ValueError(f"Missing platform weights: {args.weight_key}")
        selected = platforms[args.weight_key]
        sha = selected.get("source_sha")
        run_id = selected.get("run_id")
        root = Path(__file__).resolve().parents[2]
        excluded = "tests/generate/test_generated.py"
        files = tuple(name for name in ci_shard.inventory(root) if name != excluded)
        plan = ci_shard.make_plan(root, files, selected["weights"], args.shard_count)
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError) as error:
        parser.error(f"Invalid shard configuration: {error}")
    output.mkdir(parents=True, exist_ok=True)
    path = output / "shard-plan.json"
    ci_shard.write_plan(path, plan)
    metadata = {
        "index": args.shard_index,
        "count": args.shard_count,
        "weight_key": args.weight_key,
        "weights_path": str(args.weights.resolve()),
        "source_sha": sha,
        "run_id": run_id,
        "selected_files": plan["shards"][args.shard_index],
        "unmeasured_files": sorted(set(files) - selected["weights"].keys()),
        "excluded_files": [excluded],
        "estimated_seconds": plan["seconds"][args.shard_index],
        "plan_path": str(path),
    }
    return ["-p", "tools.suite.ci_shard", f"--ci-shard-plan={path}",
            "--ci-shard-index", str(args.shard_index), f"--ignore={excluded}"], metadata


def prior_failures_option(explicit_path, output):
    """Write valid optional CI node IDs as data for pytest's priority hook."""
    if explicit_path is not None:
        return f"--wish-prior-failures={explicit_path.resolve()}"
    raw = os.environ.get("WISH_CI_PRIOR_FAILURES_JSON", "")
    if not raw.strip():
        return None
    try:
        nodes = json.loads(raw)
    except ValueError:
        return None
    if (not isinstance(nodes, list) or not nodes
            or not all(isinstance(node, str) and node.strip()
                       and not any(ord(character) < 32 for character in node)
                       for node in nodes)):
        return None
    path = output / "prior-failures.json"
    path.write_text(json.dumps(nodes) + "\n", encoding="utf-8")
    return f"--wish-prior-failures={path}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int, default=2)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--weight-key")
    parser.add_argument("--prior-failures", type=Path)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    shard_options, shard = shard_arguments(parser, args, output)
    import psutil

    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("PYTEST_XDIST_AUTO_NUM_WORKERS", str(automatic_workers()))
    env["WISH_CI_PROFILE_DIR"] = str(output)
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    command = [sys.executable, "-m", "pytest", "-p", "tools.suite.ci_profile",
               "--durations=50", f"--junitxml={output / 'junit.xml'}", *shard_options]
    prior_option = prior_failures_option(args.prior_failures, output)
    if prior_option is not None:
        command.append(prior_option)
    command.extend(pytest_args)
    started = time.perf_counter()
    interrupted = []

    def interrupt(signum, frame):
        interrupted.append(signum)

    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    child = None
    samples = None
    exit_code = 1
    cleanup_complete = True
    try:
        child = subprocess.Popen(command, env=env)
        process = psutil.Process(child.pid)
        samples = Samples(psutil, process)
        while child.poll() is None:
            samples.take()
            if interrupted:
                break
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        exit_code = 128 + interrupted[0] if interrupted else child.returncode
    finally:
        if child is not None and child.poll() is None:
            cleanup_complete = stop_child(psutil, child)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        data = {
            "schema_version": 1,
            "command": command,
            "run_sha": os.environ.get("GITHUB_SHA"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "full_shard_run": bool(shard) and pytest_args in (
                ["-q"], ["-q", "--ignore=tests/generate/test_generated.py"]),
            "exit_code": exit_code,
            "cleanup_complete": cleanup_complete,
            "shard": shard,
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
        if not cleanup_complete:
            print("CI profile: Child process did not exit after bounded cleanup.", file=sys.stderr)
    return exit_code if exit_code >= 0 else 128 - exit_code


if __name__ == "__main__":
    raise SystemExit(main())
