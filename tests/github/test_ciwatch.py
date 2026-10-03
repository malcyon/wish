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
            item["id"]: [job(
                name, item["id"], item["id"] * 10 + offset,
                status="completed",
                conclusion="skipped" if name == ciwatch.DOCS_JOB else "success")
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
    assert set(report["workflows"][".github/workflows/test.yml"]["jobs"]) == {
        ciwatch.ROUTE_JOB,
        "generated files match their sources",
        *ciwatch.CODE_JOBS,
        ciwatch.DOCS_JOB,
    }
    assert report["workflows"][".github/workflows/test.yml"]["accepted_route"] == "code"
    assert all("head_sha=" + SHA in endpoint for endpoint, _ in transport.calls
               if "/actions/runs?" in endpoint)


def test_missing_workflow_and_completed_missing_job_wait():
    transport = Transport(runs=[run(".github/workflows/lint.yml", 10)])
    assert check(transport)["verdict"] == "pending"
    transport = Transport()
    transport.jobs[20].pop()
    report = check(transport)
    assert report["verdict"] == "pending"
    assert report["missing_jobs"][".github/workflows/test.yml"] == [
        ciwatch.DOCS_JOB]


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


def test_skipped_lint_job_cannot_pass():
    transport = Transport()
    transport.jobs[10][0]["conclusion"] = "skipped"
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
    assert check(transport)["verdict"] == "pending"
    transport = Transport()
    transport.jobs[20][0]["status"] = "in_progress"
    transport.jobs[20][0]["conclusion"] = None
    assert check(transport)["verdict"] == "pending"


def test_completed_success_run_waits_for_late_job_then_passes():
    transport = Transport()
    delayed = transport.jobs[20].pop()
    assert check(transport)["verdict"] == "pending"
    transport.jobs[20].append(delayed)
    assert check(transport)["verdict"] == "success"


def test_missing_job_times_out_without_claiming_success():
    now = [0]
    transport = Transport()
    transport.jobs[20].pop()

    def sleep(seconds):
        now[0] += seconds

    report = ciwatch.watch(SHA, timeout=3, interval=1, transport=transport,
                          clock=lambda: now[0], sleep=sleep)
    assert report["verdict"] == "timeout"
    assert report["missing_jobs"][".github/workflows/test.yml"] == [
        ciwatch.DOCS_JOB]


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
    assert len(transport.calls) == 14


def test_cli_rejects_short_sha_and_prints_compact_json(monkeypatch, capsys):
    monkeypatch.setattr(ciwatch, "watch", lambda *args, **kwargs: {
        "sha": SHA, "verdict": "success", "workflows": {},
        "missing_workflows": [], "missing_jobs": {}})
    assert ciwatch.main([SHA]) == 0
    assert json.loads(capsys.readouterr().out)["sha"] == SHA

    for value in ("nan", "inf", "-1", "0"):
        with pytest.raises(SystemExit) as exc:
            ciwatch.main([SHA, "--timeout", value])
        assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        ciwatch.main([SHA, "--shard-count", "0"])
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


def test_documentation_route_requires_generated_and_docs_attestation():
    transport = Transport()
    for item in transport.jobs[20]:
        if item["name"] in ciwatch.CODE_JOBS:
            item["conclusion"] = "skipped"
    docs = next(item for item in transport.jobs[20]
                if item["name"] == ciwatch.DOCS_JOB)
    docs["conclusion"] = "success"

    report = check(transport)
    assert report["verdict"] == "success"
    assert report["workflows"][".github/workflows/test.yml"][
        "accepted_route"] == "docs"

    transport.jobs[20].remove(docs)
    report = check(transport)
    assert report["verdict"] != "success"
    assert report["missing_jobs"][".github/workflows/test.yml"] == [
        ciwatch.DOCS_JOB]


def test_docs_route_accepts_unexpanded_or_absent_pytest_jobs():
    transport = Transport()
    route = next(item for item in transport.jobs[20]
                 if item["name"] == ciwatch.ROUTE_JOB)
    generated = next(item for item in transport.jobs[20]
                     if item["name"] == ciwatch.GENERATED_JOB)
    docs = next(item for item in transport.jobs[20]
                if item["name"] == ciwatch.DOCS_JOB)
    transport.jobs[20] = [route, generated, docs]
    docs["conclusion"] = "success"
    report = check(transport)
    assert report["verdict"] == "success"
    assert report["missing_jobs"] == {}

    transport.jobs[20] = [route, generated, docs, job(
        "pytest (, py)", 20, 210, conclusion="skipped")]
    report = check(transport)
    assert report["verdict"] == "success"
    assert report["missing_jobs"] == {}

    transport.jobs[20] = [route, generated, docs, job(
        "pytest", 20, 209, conclusion="skipped")]
    report = check(transport)
    assert report["verdict"] == "success"
    assert report["missing_jobs"] == {}


def test_docs_route_rejects_skipped_code_jobs_without_attestation():
    transport = Transport()
    for item in transport.jobs[20]:
        if item["name"] in ciwatch.CODE_JOBS:
            item["conclusion"] = "skipped"
    docs = next(item for item in transport.jobs[20]
                if item["name"] == ciwatch.DOCS_JOB)
    docs["conclusion"] = "skipped"
    assert check(transport)["verdict"] == "failure"


def test_skipped_pytest_jobs_wait_for_a_successful_docs_attestation():
    transport = Transport()
    for item in transport.jobs[20]:
        if item["name"] in ciwatch.CODE_JOBS:
            item["conclusion"] = "skipped"
    docs = next(item for item in transport.jobs[20]
                if item["name"] == ciwatch.DOCS_JOB)
    docs["status"] = "in_progress"
    docs["conclusion"] = None
    assert check(transport)["verdict"] == "pending"

    docs["status"] = "completed"
    docs["conclusion"] = "failure"
    assert check(transport)["verdict"] == "failure"


def test_active_code_and_docs_routes_are_contradictory():
    transport = Transport()
    docs = next(item for item in transport.jobs[20]
                if item["name"] == ciwatch.DOCS_JOB)
    docs["conclusion"] = "success"
    assert check(transport)["verdict"] == "failure"


def test_docs_attestation_rejects_active_or_non_skipped_pytest_jobs():
    for status, conclusion in (("in_progress", None),
                               ("completed", "success"),
                               ("completed", "failure"),
                               ("completed", "cancelled")):
        transport = Transport()
        route = next(item for item in transport.jobs[20]
                     if item["name"] == ciwatch.ROUTE_JOB)
        generated = next(item for item in transport.jobs[20]
                         if item["name"] == ciwatch.GENERATED_JOB)
        docs = next(item for item in transport.jobs[20]
                    if item["name"] == ciwatch.DOCS_JOB)
        docs["conclusion"] = "success"
        transport.jobs[20] = [route, generated, docs, job(
            "pytest (, py)", 20, 209, status=status, conclusion=conclusion)]
        assert check(transport)["verdict"] == "failure"


def test_missing_or_skipped_required_code_jobs_cannot_pass():
    transport = Transport()
    transport.jobs[20] = [item for item in transport.jobs[20]
                          if item["name"] != ciwatch.CODE_JOBS[0]]
    assert check(transport)["verdict"] != "success"

    transport = Transport()
    shard = next(item for item in transport.jobs[20]
                 if item["name"] == ciwatch.CODE_JOBS[0])
    shard["conclusion"] = "skipped"
    assert check(transport)["verdict"] == "failure"


def test_job_from_an_older_attempt_is_rejected():
    transport = Transport()
    transport.runs[1]["run_attempt"] = 2
    transport.jobs[20][0]["run_attempt"] = 1
    report = ciwatch.watch(SHA, transport=transport)
    assert report["verdict"] == "error"
    assert "stale run attempt" in report["error"]


def test_all_eight_code_shards_and_route_are_required():
    assert len(ciwatch.CODE_JOBS) == 8
    for name in (*ciwatch.CODE_JOBS, ciwatch.ROUTE_JOB):
        current = Transport()
        current.jobs[20] = [item for item in current.jobs[20]
                            if item["name"] != name]
        assert check(current)["verdict"] != "success"
        current = Transport()
        next(item for item in current.jobs[20]
             if item["name"] == name)["conclusion"] = "skipped"
        assert check(current)["verdict"] == "failure"


def test_new_failed_jobs_emit_once_while_other_jobs_finish():
    transport = Transport()
    transport.runs[1]["status"] = "in_progress"
    transport.runs[1]["conclusion"] = None
    first = next(item for item in transport.jobs[20]
                 if item["name"] == ciwatch.CODE_JOBS[0])
    second = next(item for item in transport.jobs[20]
                  if item["name"] == ciwatch.CODE_JOBS[1])
    first["conclusion"] = "failure"
    second["status"] = "in_progress"
    second["conclusion"] = None
    now = [0]
    events = []

    def sleep(seconds):
        now[0] += seconds
        if now[0] == 1:
            second["status"] = "completed"
            second["conclusion"] = "failure"
        if now[0] == 2:
            transport.runs[1]["status"] = "completed"
            transport.runs[1]["conclusion"] = "failure"

    report = ciwatch.watch(SHA, transport=transport, timeout=5, interval=1,
                          clock=lambda: now[0], sleep=sleep,
                          on_failure=events.append)
    assert report["verdict"] == "failure"
    assert now[0] == 2
    assert [event["job"] for event in events] == [first["name"], second["name"]]
    assert all(event["sha"] == SHA and event["run_id"] == 20 and
               event["job_id"] in {first["id"], second["id"]}
               for event in events)


def test_failed_run_with_absent_job_can_finish_but_not_pass():
    transport = Transport()
    transport.runs[1]["conclusion"] = "failure"
    transport.jobs[20].pop()
    report = ciwatch.watch(SHA, transport=transport, on_failure=lambda event: None)
    assert report["verdict"] == "failure"
    assert report["missing_jobs"][".github/workflows/test.yml"] == [ciwatch.DOCS_JOB]


def test_two_shard_route_requires_explicit_count():
    transport = Transport()
    transport.jobs[20] = [item for item in transport.jobs[20]
                          if item["name"] not in ciwatch.CODE_JOBS]
    transport.jobs[20].extend(
        job(name, 20, 300 + index)
        for index, name in enumerate(ciwatch.code_jobs(2))
    )
    default = check(transport)
    assert default["verdict"] != "success"
    old = ciwatch.inspect(SHA, ciwatch.DEFAULT_REPO, transport,
                          deadline=100, clock=lambda: 0, shard_count=2)
    assert old["verdict"] == "success"
