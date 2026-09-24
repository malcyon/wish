"""The CI watcher accepts only complete jobs for the requested push SHA."""

import json
import subprocess
from urllib.parse import parse_qs, urlsplit

import pytest

from tools.github import ciwatch

SHA = "a" * 40
OTHER = "b" * 40


def run(path, run_id, number=1, *, sha=SHA, event="push", status="completed",
        conclusion="success", attempt=1, branch="main"):
    return {"id": run_id, "path": path, "head_sha": sha, "event": event,
            "head_branch": branch, "run_number": number, "run_attempt": attempt,
            "status": status, "conclusion": conclusion,
            "html_url": f"https://example.test/runs/{run_id}"}


def job(name, run_id, job_id, *, status="completed", conclusion="success"):
    return {"id": job_id, "run_id": run_id, "name": name,
            "status": status, "conclusion": conclusion,
            "html_url": f"https://example.test/jobs/{job_id}"}


class Transport:
    def __init__(self, runs=None, jobs=None, page_size=None):
        self.runs = runs if runs is not None else [
            run(".github/workflows/lint.yml", 10),
            run(".github/workflows/test.yml", 20),
        ]
        self.jobs = jobs if jobs is not None else {
            item["id"]: [job(name, item["id"], item["id"] * 10 + offset)
                         for offset, name in enumerate(
                             ciwatch.WORKFLOWS.get(item["path"], ())) ]
            for item in self.runs
        }
        self.page_size = page_size
        self.calls = []

    def __call__(self, endpoint, timeout):
        self.calls.append((endpoint, timeout))
        parsed = urlsplit(endpoint)
        query = parse_qs(parsed.query)
        page = int(query["page"][0])
        assert timeout > 0
        assert query["per_page"] == ["100"]
        if parsed.path.endswith("/actions/runs"):
            assert query["head_sha"] == [SHA]
            assert query["event"] == ["push"]
            values, key = self.runs, "workflow_runs"
        else:
            run_id = int(parsed.path.split("/")[-2])
            assert query["filter"] == ["latest"]
            values, key = self.jobs[run_id], "jobs"
        size = self.page_size or 100
        return {key: values[(page - 1) * size:page * size],
                "total_count": len(values)}


def check(transport):
    return ciwatch.inspect(SHA, ciwatch.DEFAULT_REPO, transport,
                           deadline=100, clock=lambda: 0)


def test_complete_exact_push_passes():
    transport = Transport()
    report = check(transport)
    assert report["verdict"] == "success"
    assert report["missing_workflows"] == []
    assert report["missing_jobs"] == {}
    assert len(report["workflows"][".github/workflows/test.yml"]["jobs"]) == 5
    assert all("head_sha=" + SHA in endpoint for endpoint, _ in transport.calls
               if "/actions/runs?" in endpoint)


def test_missing_workflow_waits_and_completed_missing_job_fails():
    transport = Transport(runs=[run(".github/workflows/lint.yml", 10)])
    assert check(transport)["verdict"] == "pending"
    transport = Transport()
    transport.jobs[20].pop()
    report = check(transport)
    assert report["verdict"] == "failure"
    assert report["missing_jobs"][".github/workflows/test.yml"] == [
        "pytest (windows-latest, py3.13)"]


def test_wrong_sha_event_and_branch_cannot_satisfy_workflow():
    for changes in ({"sha": OTHER}, {"event": "workflow_dispatch"},
                    {"branch": "feature"}):
        transport = Transport(runs=[run(".github/workflows/lint.yml", 10),
                                    run(".github/workflows/test.yml", 20,
                                        **changes)])
        report = check(transport)
        assert report["verdict"] == "pending"
        assert report["missing_workflows"] == [".github/workflows/test.yml"]


def test_latest_run_and_latest_attempt_control_result():
    old = run(".github/workflows/test.yml", 20, number=1)
    newer = run(".github/workflows/test.yml", 21, number=2,
                status="in_progress", conclusion=None)
    transport = Transport(runs=[run(".github/workflows/lint.yml", 10), old, newer])
    transport.jobs[21] = [job(name, 21, 210 + index,
                              status="in_progress", conclusion=None)
                          for index, name in enumerate(
                              ciwatch.WORKFLOWS[".github/workflows/test.yml"])]
    report = check(transport)
    assert report["verdict"] == "pending"
    assert report["workflows"][".github/workflows/test.yml"]["id"] == 21
    newer["status"] = "completed"
    newer["conclusion"] = "failure"
    assert check(transport)["verdict"] == "failure"
    newer["run_number"] = 1
    newer["run_attempt"] = 2
    assert check(transport)["workflows"][".github/workflows/test.yml"][
        "run_attempt"] == 2


def test_cancelled_and_skipped_conclusions_fail():
    for conclusion in ("cancelled", "skipped"):
        transport = Transport()
        transport.jobs[20][0]["conclusion"] = conclusion
        assert check(transport)["verdict"] == "failure"
        transport = Transport()
        transport.runs[1]["conclusion"] = conclusion
        assert check(transport)["verdict"] == "failure"


def test_empty_conclusions_wait_for_a_definitive_result():
    for conclusion in (None, ""):
        transport = Transport()
        transport.jobs[20][0]["conclusion"] = conclusion
        assert check(transport)["verdict"] == "pending"
        transport = Transport()
        transport.runs[1]["conclusion"] = conclusion
        assert check(transport)["verdict"] == "pending"


def test_empty_jobs_cannot_pass_and_pending_jobs_wait():
    transport = Transport()
    transport.jobs[20] = []
    assert check(transport)["verdict"] == "failure"
    transport = Transport()
    transport.runs[1]["status"] = "in_progress"
    transport.runs[1]["conclusion"] = None
    transport.jobs[20][0]["status"] = "in_progress"
    transport.jobs[20][0]["conclusion"] = None
    assert check(transport)["verdict"] == "pending"


def test_timeout_and_api_error_are_bounded():
    now = [0]
    transport = Transport(runs=[])

    def sleep(seconds):
        now[0] += seconds

    report = ciwatch.watch(SHA, timeout=5, interval=2, transport=transport,
                          clock=lambda: now[0], sleep=sleep)
    assert report["verdict"] == "timeout"
    assert now[0] == 5
    assert len(transport.calls) == 3

    def broken(endpoint, timeout):
        raise ciwatch.CIWatchError("offline")

    report = ciwatch.watch(SHA, transport=broken)
    assert report["verdict"] == "error"
    assert report["error"] == "offline"


def test_paginates_runs_and_jobs():
    runs = [run(".github/workflows/lint.yml", 10),
            run(".github/workflows/test.yml", 20)]
    transport = Transport(runs=runs, page_size=1)
    assert check(transport)["verdict"] == "success"
    assert len(transport.calls) == 8


def test_cli_rejects_short_sha_and_prints_compact_json(monkeypatch, capsys):
    monkeypatch.setattr(ciwatch, "watch", lambda *args: {
        "sha": SHA, "verdict": "success", "workflows": {},
        "missing_workflows": [], "missing_jobs": {}})
    assert ciwatch.main([SHA]) == 0
    assert json.loads(capsys.readouterr().out)["sha"] == SHA

    for value in ("nan", "inf", "-1", "0"):
        with pytest.raises(SystemExit) as exc:
            ciwatch.main([SHA, "--timeout", value])
        assert exc.value.code == 2


def test_gh_transport_uses_get_and_a_per_command_timeout(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, 0, '{"total_count":0,"jobs":[]}', "")

    monkeypatch.setattr(ciwatch.subprocess, "run", fake_run)
    assert ciwatch.gh_get("/repos/malcyon/wish/actions/runs", 12)["jobs"] == []
    assert captured["command"] == [
        "gh", "api", "--method", "GET", "/repos/malcyon/wish/actions/runs"]
    assert captured["kwargs"]["timeout"] == 12
