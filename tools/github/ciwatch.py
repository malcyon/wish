#!/usr/bin/env python3
"""Wait for the required push workflows and jobs for one exact commit SHA."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from urllib.parse import urlencode

DEFAULT_REPO = "malcyon/wish"
WORKFLOWS = {
    ".github/workflows/lint.yml": ("ruff",),
    ".github/workflows/test.yml": (
        "generated files match their sources",
        "pytest (ubuntu-latest, py3.12)",
        "pytest (ubuntu-latest, py3.13)",
        "pytest (windows-latest, py3.12)",
        "pytest (windows-latest, py3.13)",
    ),
}
PAGE_SIZE = 100
MAX_PAGES = 100
GH_TIMEOUT = 20
ACTIVE_STATUSES = {"queued", "in_progress", "requested", "waiting", "pending"}


class CIWatchError(Exception):
    """The GitHub result could not be trusted."""


def gh_get(endpoint: str, timeout: float) -> dict:
    """Fetch one REST page through gh without allowing an implicit POST."""
    try:
        done = subprocess.run(
            ["gh", "api", "--method", "GET", endpoint],
            capture_output=True, text=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CIWatchError(f"gh api could not complete: {exc}") from exc
    if done.returncode:
        raise CIWatchError(f"gh api failed: {(done.stderr or done.stdout).strip()}")
    try:
        result = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise CIWatchError(f"gh api returned invalid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise CIWatchError("gh api returned a non-object")
    return result


def pages(transport, path: str, key: str, params: dict, deadline: float,
          clock=time.monotonic) -> list[dict]:
    """Read every page, including runs beyond GitHub's first 100 results."""
    items = []
    for page in range(1, MAX_PAGES + 1):
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("CI monitoring deadline reached")
        query = urlencode({**params, "per_page": PAGE_SIZE, "page": page})
        response = transport(f"{path}?{query}", min(GH_TIMEOUT, remaining))
        batch = response.get(key)
        total = response.get("total_count")
        if not isinstance(batch, list) or not isinstance(total, int) or total < 0:
            raise CIWatchError(f"GitHub returned invalid {key} pagination")
        if any(not isinstance(item, dict) for item in batch):
            raise CIWatchError(f"GitHub returned a non-object {key} entry")
        items.extend(batch)
        if len(items) >= total:
            return items
        if not batch:
            raise CIWatchError(f"GitHub stopped paginating {key} before total_count")
    raise CIWatchError(f"GitHub {key} exceeded {MAX_PAGES} pages")


def _summary(record: dict) -> dict:
    return {key: record.get(key) for key in
            ("id", "html_url", "status", "conclusion")}


def inspect(sha: str, repo: str, transport, deadline: float,
            clock=time.monotonic) -> dict:
    """Return one complete snapshot; no missing or stale result can pass."""
    base = f"/repos/{repo}/actions"
    runs = pages(transport, f"{base}/runs", "workflow_runs",
                 {"head_sha": sha, "event": "push"}, deadline, clock)
    selected = {}
    for run in runs:
        path = run.get("path")
        if path not in WORKFLOWS or run.get("head_sha") != sha:
            continue
        if run.get("event") != "push":
            continue
        if run.get("head_branch") != "main":
            continue
        if not isinstance(run.get("id"), int):
            raise CIWatchError("Required workflow run has no numeric ID")
        if not isinstance(run.get("run_number"), int) or not isinstance(
                run.get("run_attempt"), int):
            raise CIWatchError("Required workflow run has no run number/attempt")
        previous = selected.get(path)
        rank = (run["run_number"], run["run_attempt"], run["id"])
        if previous is None or rank > previous[0]:
            selected[path] = (rank, run)

    report = {"sha": sha, "verdict": "pending", "workflows": {},
              "missing_workflows": [], "missing_jobs": {}}
    failed = False
    for path, expected in WORKFLOWS.items():
        if path not in selected:
            report["missing_workflows"].append(path)
            continue
        run = selected[path][1]
        entry = _summary(run)
        entry["run_attempt"] = run["run_attempt"]
        entry["jobs"] = {}
        report["workflows"][path] = entry
        if (run.get("status") == "completed" and
                run.get("conclusion") not in (None, "", "success")):
            failed = True
        elif run.get("status") not in ACTIVE_STATUSES | {"completed"}:
            failed = True

        jobs = pages(transport, f"{base}/runs/{run['id']}/jobs", "jobs",
                     {"filter": "latest"}, deadline, clock)
        matched = {}
        for job in jobs:
            name = job.get("name")
            if name not in expected:
                continue
            if name in matched:
                raise CIWatchError(f"Duplicate latest job: {name}")
            if not isinstance(job.get("id"), int):
                raise CIWatchError(f"Required job has no numeric ID: {name}")
            if job.get("run_id") != run["id"]:
                raise CIWatchError(f"Required job belongs to another run: {name}")
            matched[name] = job
            entry["jobs"][name] = _summary(job)
            if (job.get("status") == "completed" and
                    job.get("conclusion") not in (None, "", "success")):
                failed = True
            elif job.get("status") not in ACTIVE_STATUSES | {"completed"}:
                failed = True
        missing = [name for name in expected if name not in matched]
        if missing:
            report["missing_jobs"][path] = missing
        if run.get("status") == "completed" and missing:
            failed = True
        if run.get("status") == "completed" and run.get("conclusion") == "success":
            if any(job.get("status") != "completed" or
                   job.get("conclusion") not in (None, "", "success")
                   for job in matched.values()):
                failed = True

    if failed:
        report["verdict"] = "failure"
    elif not report["missing_workflows"] and not report["missing_jobs"] and all(
            entry["status"] == "completed" and entry["conclusion"] == "success"
            and all(job["status"] == "completed" and job["conclusion"] == "success"
                    for job in entry["jobs"].values())
            for entry in report["workflows"].values()):
        report["verdict"] = "success"
    return report


def watch(sha: str, repo: str = DEFAULT_REPO, timeout: float = 1200,
          interval: float = 30, transport=gh_get, clock=time.monotonic,
          sleep=time.sleep) -> dict:
    """Poll internally until success, failure, error, or a monotonic deadline."""
    deadline = clock() + timeout
    report = {"sha": sha, "verdict": "timeout", "workflows": {},
              "missing_workflows": list(WORKFLOWS), "missing_jobs": {}}
    while True:
        try:
            report = inspect(sha, repo, transport, deadline, clock)
        except TimeoutError:
            report["verdict"] = "timeout"
            return report
        except CIWatchError as exc:
            report["verdict"] = "error"
            report["error"] = str(exc)
            return report
        if report["verdict"] != "pending":
            return report
        remaining = deadline - clock()
        if remaining <= 0:
            report["verdict"] = "timeout"
            return report
        sleep(min(interval, remaining))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sha", help="Full pushed commit SHA")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.sha):
        parser.error("SHA must be 40 hexadecimal characters")
    if (not math.isfinite(args.timeout) or args.timeout <= 0 or
            not math.isfinite(args.interval) or args.interval <= 0):
        parser.error("Timeout and interval must be finite and positive")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("Repository must be owner/name")
    report = watch(args.sha.lower(), args.repo, args.timeout, args.interval)
    print(json.dumps(report, separators=(",", ":")))
    return {"success": 0, "timeout": 2, "failure": 1, "error": 1}[report["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
