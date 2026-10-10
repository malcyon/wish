"""`tools/suite/testrun.py` and `tools/suite/testcontrol.py`: one test command at a time, inside the limited service.

The systemd and cgroup layer is replaced by a fake whose clock advances only when
the code sleeps, so every ordering below is deterministic and no test waits.
The policy, the lock files and the state directory are temporary files; the real
host policy is never read, because the production path is a constant that no
environment variable changes.
"""

from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys
import textwrap

import pytest

from tools.suite import testcontrol, testrun

REPO = pathlib.Path(__file__).resolve().parents[2]
LIMIT = 8 * 1024 ** 3
UID = os.getuid() if hasattr(os, "getuid") else 1000
SLICE_CG = f"/user.slice/user-{UID}.slice/user@{UID}.service/wish.slice/wish-tests.slice"


# --- fixtures -------------------------------------------------------------------

def _policy_data(tmp_path, **changes):
    data = {"schema_version": 1, "enabled": True, "uid": UID,
            "slice": "wish-tests.slice", "service": "wish-tests-run.service",
            "execution_lock": str(tmp_path / "run" / "execution.lock"),
            "control_lock": str(tmp_path / "run" / "control.lock"),
            "state_dir": str(tmp_path / "state"), "memory_max_bytes": LIMIT,
            "allowed_environment": ["HOME", "PATH", "PYTEST_ADDOPTS", "PYTHONPATH"]}
    data.update(changes)
    return data


def _write_policy(tmp_path, **changes):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(_policy_data(tmp_path, **changes)), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _scratch_in_tmp(tmp_path, monkeypatch):
    """The launcher's log and report files go to the scratch directory."""
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()


@pytest.fixture
def policy(tmp_path):
    (tmp_path / "run").mkdir()
    for name in ("execution.lock", "control.lock"):
        (tmp_path / "run" / name).write_text("")
    return testcontrol.read_policy(_write_policy(tmp_path))


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")

    def git(*args):
        subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                        *args], check=True, capture_output=True)
    git("init", "-q")
    git("add", ".")
    git("commit", "-q", "-m", "first")
    return root


class Clock:
    """Time that moves only when the code sleeps, then lets the test react."""

    def __init__(self):
        self.now = 1_000_000.0
        self.on_sleep = None
        self.sleeps = 0
        self.slept = []

    #: A loop that never ends must fail the test rather than hang the run.
    CEILING = 100_000

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps += 1
        assert self.sleeps <= self.CEILING, "the code under test is looping forever"
        self.slept.append(seconds)
        if self.on_sleep:
            self.on_sleep()


class FakeBackend:
    """A user manager with one fixed service and a slice cgroup."""

    def __init__(self):
        self.unit = {"LoadState": "not-found"}
        self.started, self.stopped, self.inside = [], [], False
        self.cgroup_present = False
        self.populated = None
        self.memory_max = LIMIT
        self.count = 0

    def slice_info(self, policy):
        return {"cgroup": SLICE_CG, "memory_max": self.memory_max, "swap_max": "0"}

    def slice_events(self, cgroup):
        return {"oom": 0, "oom_kill": 0}

    def unit_state(self, unit):
        return dict(self.unit)

    def start(self, spec):
        if self.unit.get("LoadState") != "not-found":
            raise testrun.LaunchError("systemd-run failed: unit already exists")
        self.count += 1
        self.started.append(spec)
        self.unit = {"LoadState": "loaded", "ActiveState": "active", "SubState": "running",
                     "Description": spec["description"], "InvocationID": f"inv{self.count}",
                     "Job": ""}
        return f"inv{self.count}"

    def stop(self, unit):
        self.stopped.append(self.unit.get("InvocationID"))
        self.unit = {"LoadState": "not-found"}

    def reset_failed(self, unit):
        pass

    def cgroup_exists(self, cgroup):
        return self.cgroup_present

    def cgroup_populated(self, cgroup):
        return self.populated

    def sample(self, cgroup):
        return {"procs": [(1, "python"), (2, "python"), (3, "python"), (4, "bash")],
                "peak": 5000, "oom_group": "1", "events": {}}

    def inside_service(self, policy):
        return self.inside

    def finish(self, result="success", code="1", status="0"):
        self.unit.update(ActiveState="active" if result == "success" else "failed",
                         SubState="exited" if result == "success" else "failed",
                         Result=result, ExecMainCode=code, ExecMainStatus=status)

    def run_elsewhere(self, request_id, invocation, active="active", sub="running"):
        self.unit = {"LoadState": "loaded", "ActiveState": active, "SubState": sub,
                     "Description": f"wish-tests {request_id}", "InvocationID": invocation,
                     "Job": ""}


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def ctx(policy, backend, clock):
    return testrun.Context(policy, backend, clock=clock, sleep=clock.sleep,
                           err=open(os.devnull, "w"))


def register(ctx, repo, request_id="r1", **kw):
    kw.setdefault("pytest_args", ["-n0", "tests/test_a.py"])
    kw.setdefault("ruff", False)
    kw.setdefault("genui", False)
    kw.setdefault("environ", {"HOME": "/h", "PATH": "/bin", "SECRET_TOKEN": "x"})
    record, _ = testrun.register_request(
        ctx, request_id=request_id, session="s1", requester="agent-1",
        workdir=str(repo), **kw)
    return record


def mark(ctx, request_id, status, invocation=None):
    record = testrun.read_record(ctx.policy, request_id)
    record.update(status=status, invocation_id=invocation, run_cgroup=SLICE_CG + "/svc",
                  started_epoch=ctx.clock(), deadline_epoch=ctx.clock() + 100,
                  checks_file=None)
    testrun.write_record(ctx.policy, record)
    return record


def hold(path):
    fcntl = pytest.importorskip("fcntl")
    fd = os.open(path, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def write_report(record, **checks):
    """What the wrapper inside the service writes when it finishes."""
    report = {"complete": True, "memory": {"peak": 7000, "oom": 0, "oom_kill": 0},
              "checks": {name: {"returncode": code, "elapsed": 1.0, "counts": {"passed": 3},
                                "tail": "" if code == 0 else "boom"}
                         for name, code in (checks or {"pytest": 0}).items()}}
    pathlib.Path(record["checks_file"]).write_text(json.dumps(report))


# --- the policy -------------------------------------------------------------------

def test_a_valid_policy_is_parsed(tmp_path):
    parsed = testcontrol.read_policy(_write_policy(tmp_path))
    assert parsed.slice == "wish-tests.slice" and parsed.memory_max_bytes == LIMIT
    assert parsed.allowed_environment[0] == "HOME"


@pytest.mark.parametrize("change, message", [
    ({"schema_version": 2}, "schema_version"),
    ({"schema_version": True}, "schema_version"),
    ({"enabled": "yes"}, "enabled must be bool"),
    ({"memory_max_bytes": True}, "memory_max_bytes must be int"),
    ({"memory_max_bytes": 0}, "positive"),
    ({"allowed_environment": "HOME"}, "allowed_environment must be list"),
    ({"slice": ""}, "slice is empty"),
])
def test_a_wrong_policy_is_named_precisely(tmp_path, change, message):
    with pytest.raises(testcontrol.PolicyError, match=message):
        testcontrol.read_policy(_write_policy(tmp_path, **change))


def test_a_missing_key_a_missing_file_and_bad_json_are_distinct(tmp_path):
    data = _policy_data(tmp_path)
    del data["uid"]
    path = tmp_path / "p.json"
    path.write_text(json.dumps(data))
    with pytest.raises(testcontrol.PolicyError, match="missing the key uid"):
        testcontrol.read_policy(path)
    with pytest.raises(testcontrol.PolicyMissing):
        testcontrol.read_policy(tmp_path / "absent.json")
    path.write_text("{")
    with pytest.raises(testcontrol.PolicyError, match="not valid JSON"):
        testcontrol.read_policy(path)


# --- registering a request -----------------------------------------------------------

def test_a_request_records_the_commit_the_files_the_argv_and_only_allowed_environment(
        ctx, repo):
    (repo / "tests" / "test_b.py").write_text("x = 1\n")
    record = register(ctx, repo, files=["tests/test_b.py", "tests/gone.py"])
    request = record["request"]
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    assert record["status"] == "pending" and request["head"] == head
    assert request["files"]["tests/gone.py"] == "missing"
    assert len(request["files"]["tests/test_b.py"]) == 64
    assert request["files"]["tests/test_a.py"] != "missing"
    assert request["env"] == {"HOME": "/h", "PATH": "/bin"}
    assert request["checks"][0]["argv"][1:] == ["-m", "pytest", "-n0", "tests/test_a.py"]
    assert "tests/test_b.py" in record["dirty"]


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="file modes are POSIX")
def test_a_record_file_is_mode_0600(ctx, repo):
    register(ctx, repo)
    path = pathlib.Path(ctx.policy.state_dir) / "r1.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_resubmitting_the_same_request_returns_it_and_different_content_is_an_error(
        ctx, repo):
    first = register(ctx, repo)
    again, created = testrun.register_request(
        ctx, request_id="r1", session="s1", requester="agent-1", workdir=str(repo),
        pytest_args=["-n0", "tests/test_a.py"], ruff=False, genui=False,
        environ={"HOME": "/h", "PATH": "/bin"})
    assert not created and again["submitted"] == first["submitted"]
    with pytest.raises(testrun.LaunchError, match="different request"):
        register(ctx, repo, pytest_args=["-n0", "-k", "other"])
    assert len(testrun.all_records(ctx.policy)) == 1


def test_an_invalid_id_a_long_timeout_and_a_memory_limit_that_does_not_lower_are_rejected(
        ctx, repo):
    with pytest.raises(testrun.LaunchError, match="valid request ID"):
        register(ctx, repo, request_id="../x")
    with pytest.raises(testrun.LaunchError, match="--timeout"):
        register(ctx, repo, timeout=testrun.MAX_TIMEOUT + 1)
    with pytest.raises(testrun.LaunchError, match="--memory-max"):
        register(ctx, repo, memory_max=LIMIT)


def test_a_whole_suite_request_may_run_longer_and_says_to_use_stages(ctx, repo):
    record, _ = testrun.register_request(
        ctx, request_id="suite", session="s1", requester="x", workdir=str(repo),
        suiterun_args=["HEAD", "--keep"], timeout=3000, environ={})
    assert record["request"]["kind"] == "suiterun" and record["request"]["timeout"] == 3000
    assert record["request"]["checks"][0]["argv"][-2:] == ["HEAD", "--keep"]
    assert "run ID" in record["note"]


# --- running ---------------------------------------------------------------------------

def _finishing(clock, backend, ctx, request_id="r1", **finish):
    """After the first poll the service ends and its report is on disk."""
    def react():
        record = testrun.read_record(ctx.policy, request_id)
        write_report(record, **finish.pop("checks", {"pytest": 0}))
        backend.finish(**finish)
        clock.on_sleep = None
    clock.on_sleep = react


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_clean_run_passes_only_when_every_condition_holds(ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    _finishing(clock, backend, ctx)
    view = testrun.run_request(ctx, "r1")
    result = view["result"]
    assert view["status"] == "passed" and result["conditions_unmet"] == []
    assert result["exit"] == {"Result": "success", "ExecMainCode": "1", "ExecMainStatus": "0"}
    assert result["pytest_processes"] == 2 and result["memory_peak_bytes"] == 7000
    assert result["cleanup"]["complete"] and result["valid_as_acceptance"]
    assert backend.unit == {"LoadState": "not-found"}
    spec = backend.started[0]
    assert spec["description"] == "wish-tests r1" and spec["env"] == {"HOME": "/h", "PATH": "/bin"}
    assert testrun.read_record(ctx.policy, "r1")["invocation_id"] == "inv1"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
@pytest.mark.parametrize("finish, checks, expect", [
    (dict(result="exit-code", code="1", status="1"), {"pytest": 1}, "failed"),
    (dict(result="success", code="2", status="0"), {"pytest": 0}, "failed"),
    (dict(result="success", code="1", status="3"), {"pytest": 0}, "failed"),
    (dict(result="success", code="1", status="0"), {"pytest": 1}, "failed"),
    (dict(result="timeout", code="2", status="15"), {"pytest": 0}, "timed_out"),
])
def test_any_single_unmet_condition_is_not_a_pass(ctx, repo, backend, clock, finish, checks, expect):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    _finishing(clock, backend, ctx, checks=checks, **finish)
    view = testrun.run_request(ctx, "r1")
    assert view["status"] == expect and view["result"]["conditions_unmet"]
    assert not view["result"]["valid_as_acceptance"]


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_missing_report_is_not_a_pass_even_with_a_clean_exit(ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    clock.on_sleep = lambda: backend.finish()
    view = testrun.run_request(ctx, "r1")
    assert view["status"] == "interrupted"
    assert "check pytest did not report" in view["result"]["conditions_unmet"]
    assert view["result"]["checks_not_run"] == ["pytest"]


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_cgroup_that_stays_populated_is_an_infrastructure_failure_and_blocks_the_next_run(
        ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    register(ctx, repo, request_id="r2", pytest_args=["-n0", "-k", "two"])
    backend.cgroup_present, backend.populated = True, True
    _finishing(clock, backend, ctx)
    view = testrun.run_request(ctx, "r1")
    assert view["status"] == "infrastructure_failure"
    assert not view["result"]["cleanup"]["complete"]
    backend.run_elsewhere("r1", "inv1", "deactivating", "stop-sigterm")
    second = testrun.run_request(ctx, "r2", admission_timeout=3)
    assert second["status"] == "pending" and second["blocked_by"] == "r1"
    assert len(backend.started) == 1


def test_the_unmet_condition_list_names_a_foreign_invocation():
    state = {"InvocationID": "other", "Result": "success", "ExecMainCode": "1",
             "ExecMainStatus": "0"}
    report = {"complete": True, "checks": {"pytest": {"returncode": 0}}}
    assert testrun.unmet_conditions(state, "mine", report, ["pytest"], True)
    assert not testrun.unmet_conditions(state, "other", report, ["pytest"], True)
    assert testrun.unmet_conditions(state, "other", report, ["pytest"], False)


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_files_changed_before_the_start_make_the_request_stale_and_nothing_starts(
        ctx, repo, backend):
    pytest.importorskip("fcntl")
    register(ctx, repo, files=["tests/test_a.py"])
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert False\n")
    view = testrun.run_request(ctx, "r1")
    assert view["status"] == "stale" and "tests/test_a.py" in view["result"]["changed"]
    assert backend.started == []


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_files_changed_during_the_run_mark_the_result_as_no_acceptance_evidence(
        ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo, files=["tests/test_a.py"])

    def react():
        (repo / "tests" / "test_a.py").write_text("# edited mid-run\n")
        write_report(testrun.read_record(ctx.policy, "r1"))
        backend.finish()
        clock.on_sleep = None
    clock.on_sleep = react
    view = testrun.run_request(ctx, "r1")
    assert view["status"] == "passed" and not view["result"]["valid_as_acceptance"]
    assert view["result"]["files_changed_during_run"] == ["tests/test_a.py"]


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_an_admission_timeout_leaves_the_request_pending_and_starts_nothing(
        ctx, repo, backend, policy, capsys):
    register(ctx, repo)
    busy = hold(policy.execution_lock)
    try:
        view = testrun.run_request(ctx, "r1", admission_timeout=2)
    finally:
        os.close(busy)
    assert view["status"] == "pending" and view["admitted"] is False
    assert backend.started == []
    assert testrun.read_record(policy, "r1")["status"] == "pending"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_limit_that_is_not_the_policys_starts_nothing(ctx, repo, backend):
    register(ctx, repo)
    backend.memory_max = LIMIT * 2
    with pytest.raises(testrun.LaunchError, match="memory.max"):
        testrun.run_request(ctx, "r1")
    assert backend.started == [] and testrun.read_record(ctx.policy, "r1")["status"] == "pending"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_finished_request_is_never_run_again(ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    _finishing(clock, backend, ctx)
    testrun.run_request(ctx, "r1")
    again = testrun.run_request(ctx, "r1")
    assert again["status"] == "passed" and len(backend.started) == 1


# --- reconcile -------------------------------------------------------------------------

@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_running_service_blocks_admission_and_is_left_alone(ctx, repo, backend):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    backend.run_elsewhere("other", "invX")
    settled = testrun.reconcile_service(ctx)
    assert settled["state"] == "blocked" and settled["request"] == "other"
    view = testrun.run_request(ctx, "r1", admission_timeout=2)
    assert view["status"] == "pending" and view["blocked_by"] == "other"
    assert backend.stopped == [] and backend.started == []


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_failed_service_is_finalised_from_its_record_and_unloaded(ctx, repo, backend, tmp_path):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    record = mark(ctx, "r1", "running", "invF")
    record["checks_file"] = str(tmp_path / "checks.json")
    testrun.write_record(ctx.policy, record)
    write_report(record, pytest=1)
    backend.run_elsewhere("r1", "invF", "failed", "failed")
    backend.finish("exit-code", "1", "1")
    settled = testrun.reconcile_service(ctx)
    assert settled == {"state": "free", "finalized": ["r1"]}
    assert testrun.read_record(ctx.policy, "r1")["status"] == "failed"
    assert backend.unit == {"LoadState": "not-found"}


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
@pytest.mark.parametrize("status", ["starting", "running"])
def test_a_record_left_active_with_no_service_becomes_interrupted(ctx, repo, backend, status):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    mark(ctx, "r1", status, "invGone")
    assert testrun.reconcile_service(ctx)["state"] == "free"
    record = testrun.read_record(ctx.policy, "r1")
    assert record["status"] == "interrupted" and record["result"]["reason"]


# --- cancel ----------------------------------------------------------------------------

@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
@pytest.mark.parametrize("holder, invocation", [("r1", "invNEW"), ("r2", "invOLD")])
def test_a_stale_cancel_never_stops_a_different_request_or_invocation(
        ctx, repo, backend, holder, invocation):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    mark(ctx, "r1", "running", "invOLD")
    backend.run_elsewhere(holder, invocation)
    outcome = testrun.cancel_request(ctx, "r1")
    assert backend.stopped == [] and outcome["stopped"] is False
    assert backend.unit["InvocationID"] == invocation
    assert testrun.read_record(ctx.policy, "r1")["status"] == "interrupted"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_cancel_stops_the_matching_invocation_and_records_cancelled(ctx, repo, backend):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    mark(ctx, "r1", "running", "invOLD")
    backend.run_elsewhere("r1", "invOLD")
    outcome = testrun.cancel_request(ctx, "r1")
    assert backend.stopped == ["invOLD"] and outcome["status"] == "cancelled"
    assert outcome["stopped"] is True


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_cancelling_a_pending_request_stops_no_service(ctx, repo, backend):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    assert testrun.cancel_request(ctx, "r1")["status"] == "cancelled"
    assert backend.stopped == []


# --- nesting -----------------------------------------------------------------------------

@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_nested_run_executes_in_process_without_a_service_or_the_execution_lock(
        ctx, repo, backend, policy):
    register(ctx, repo)
    record = testrun.read_record(policy, "r1")
    record["request"]["checks"] = [{"name": "pytest", "argv": [
        sys.executable, "-c", "print('3 passed in 0.01s')"]}]
    testrun.write_record(policy, record)
    backend.inside = True
    backend.run_elsewhere("parent", "invP")
    parent = {**record, "id": "parent", "status": "running", "invocation_id": "invP",
              "deadline_epoch": ctx.clock() + 100}
    testrun.write_record(policy, parent)
    held = [hold(policy.execution_lock)]
    try:
        view = testrun.run_request(ctx, "r1")
    finally:
        for fd in held:
            os.close(fd)
    assert view["status"] == "passed" and view["nested"] is True
    assert view["result"]["counts"] == {"passed": 3}
    assert backend.started == [] and backend.stopped == []


# --- the guard ----------------------------------------------------------------------------

def _guard_host(tmp_path, *, inside, limit=LIMIT, enabled=True):
    policy_path = _write_policy(tmp_path, enabled=enabled)
    root = tmp_path / "cg"
    slice_dir = root / SLICE_CG.lstrip("/")
    slice_dir.mkdir(parents=True)
    (slice_dir / "memory.max").write_text(f"{limit}\n")
    proc = tmp_path / "proc_cgroup"
    where = SLICE_CG + ("/wish-tests-run.service/sub" if inside else "/../session-3.scope")
    proc.write_text(f"0::{where}\n")

    return dict(policy_path=policy_path, platform="linux", proc_cgroup_file=proc,
                cgroup_root=str(root))


def test_a_disabled_or_absent_policy_leaves_pytest_alone(tmp_path):
    assert testcontrol.guard_message(**_guard_host(tmp_path, inside=False, enabled=False)) is None
    assert testcontrol.guard_message(tmp_path / "none.json", platform="linux") is None


def test_an_enabled_policy_stops_pytest_outside_the_service_even_with_ci_set(
        tmp_path, monkeypatch):
    monkeypatch.setenv("CI", "1")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.setenv("WISH_TEST_REQUEST", "r1")
    message = testcontrol.guard_message(**_guard_host(tmp_path, inside=False))
    assert "testrun.py submit" in message and "wish-tests-run.service" in message


def test_an_enabled_policy_lets_pytest_inside_the_service_or_a_descendant_run(tmp_path):
    assert testcontrol.guard_message(**_guard_host(tmp_path, inside=True)) is None


def test_a_slice_with_the_wrong_limit_stops_even_inside_the_service(tmp_path):
    message = testcontrol.guard_message(**_guard_host(tmp_path, inside=True, limit=LIMIT * 2))
    assert "memory.max" in message


def test_a_malformed_policy_stops_pytest_rather_than_lifting_the_guard(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text("{}")
    assert "unusable" in testcontrol.guard_message(path, platform="linux")


def test_remote_xdist_is_stopped_inside_the_service_and_local_workers_are_not(tmp_path):
    host = _guard_host(tmp_path, inside=True)
    assert "ssh=box" in testcontrol.guard_message(**host, tx=["4*popen", "ssh=box"])
    assert testcontrol.guard_message(**host, tx=["4*popen//python=python3"]) is None


def test_other_platforms_have_no_guard(tmp_path):
    host = _guard_host(tmp_path, inside=False)
    host["platform"] = "win32"
    assert testcontrol.guard_message(**host) is None


def test_the_conftest_hook_exits_with_status_four_on_a_message_and_not_otherwise():
    import ast
    tree = ast.parse((REPO / "tests" / "conftest.py").read_text(encoding="utf-8"))
    hook = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "pytest_configure")
    decorator = ast.unparse(hook.decorator_list[0]) if hook.decorator_list else ""
    assert decorator == "pytest.hookimpl(tryfirst=True)", "the hook must run before xdist starts workers"
    answers = {"text": "stopped"}

    class Control:
        @staticmethod
        def guard_message(tx=None):
            return answers["text"]
    names = {"pytest": pytest, "_testcontrol": Control}
    exec(compile(ast.Module([hook], []), "conftest", "exec"), names)
    config = type("C", (), {"option": type("O", (), {"tx": ["popen"]})})()
    with pytest.raises(pytest.exit.Exception) as caught:
        names["pytest_configure"](config)
    assert caught.value.returncode == 4
    answers["text"] = None
    names["pytest_configure"](config)


def test_the_modules_import_where_there_is_no_fcntl_and_the_platform_is_windows():
    script = textwrap.dedent("""
        import argparse, collections, contextlib, dataclasses, datetime, hashlib, json
        import pathlib, re, secrets, subprocess, tempfile, time
        import sys
        sys.modules['fcntl'] = None
        sys.platform = 'win32'
        from tools.suite import testcontrol, testrun
        assert testcontrol.guard_message() is None
        assert testrun.SystemBackend().inside_service(None) is False
        """)
    done = subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True,
                          text=True, env={**os.environ, "PYTHONPATH": str(REPO)})
    assert done.returncode == 0, done.stderr


# --- findings from review ------------------------------------------------------------------

def _fake_run(calls, stderr="Running as unit: x; invocation ID: " + "ab" * 16 + "\n"):
    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, "", stderr)
    return run


def test_the_service_is_started_with_an_exact_systemd_run_argv_and_no_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(testrun.subprocess, "run", _fake_run(calls))
    spec = {"unit": "wish-tests-run.service", "slice": "wish-tests.slice",
            "description": "wish-tests r1", "workdir": "/w", "env": {"HOME": "/h", "A": "$B"},
            "runtime_max": 450, "memory_max": None, "log": "/l/r1.log",
            "argv": ["/py", "/x/testrun.py", "_wrap", "/s/r1.json"]}
    assert testrun.SystemBackend().start(spec) == "ab" * 16
    argv, kw = calls[0]
    assert isinstance(argv, list) and not kw.get("shell")
    assert argv[:2] == ["systemd-run", "--user"]
    assert "--expand-environment=no" in argv and "--replace" not in argv
    assert [a for a in argv if a.startswith("--setenv=")] == ["--setenv=HOME=/h", "--setenv=A=$B"]
    pairs = {a for i, a in enumerate(argv) if i and argv[i - 1] == "-p"}
    for wanted in ("Type=exec", "ExitType=main", "KillMode=control-group", "OOMPolicy=kill",
                   "Restart=no", "RuntimeMaxSec=450", "TimeoutStopSec=15s", "MemorySwapMax=0"):
        assert wanted in pairs
    assert argv[argv.index("--") + 1:] == spec["argv"]
    assert kw["timeout"] == testrun.SYSTEMD_RUN_TIMEOUT


def test_a_systemd_run_failure_is_a_launch_error(monkeypatch):
    monkeypatch.setattr(testrun.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 1, "", "no"))
    with pytest.raises(testrun.LaunchError, match="systemd-run failed: no"):
        testrun.SystemBackend().start({
            "unit": "u", "slice": "s", "description": "d", "workdir": "/w", "env": {},
            "runtime_max": 1, "log": "/l", "argv": ["x"]})


def test_the_wrapper_runs_every_check_reports_each_and_exits_nonzero_on_any_failure(
        tmp_path, policy, repo, monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-p no:cacheprovider")
    checks_file = tmp_path / "checks.json"
    request = {"workdir": str(repo), "pytest_args": ["-n0"], "env": {},
               "checks": [{"name": "pytest", "argv": [sys.executable, "-c", "print('1 passed in 0.01s')"]},
                          {"name": "ruff", "argv": [sys.executable, "-c", "raise SystemExit(3)"]},
                          {"name": "genui", "argv": [sys.executable, "-c", "pass"]}]}
    record = {"id": "r1", "checks_file": str(checks_file), "request": request}
    path = tmp_path / "r1.json"
    path.write_text(json.dumps(record))
    assert testrun.wrap(str(path)) == 1
    report = json.loads(checks_file.read_text())
    assert report["complete"] is True
    assert {n: c["returncode"] for n, c in report["checks"].items()} == {
        "pytest": 0, "ruff": 3, "genui": 0}
    assert report["checks"]["pytest"]["counts"] == {"passed": 1}
    assert report["effective"]["PYTEST_ADDOPTS"] == "-p no:cacheprovider"
    assert report["effective"]["pytest_argv"][-1].startswith("print(")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_service_that_outlives_its_deadline_and_grace_is_stopped_and_recorded_timed_out(
        ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    view = testrun.run_request(ctx, "r1")
    assert backend.stopped == ["inv1"]
    assert view["status"] == "timed_out"
    assert testrun.read_record(ctx.policy, "r1")["timeout_enforced"] is True
    assert clock.now >= 1_000_000.0 + testrun.DEFAULT_TIMEOUT + testrun.GRACE


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_failed_state_query_never_unloads_or_stops_and_leaves_the_record_active(
        ctx, repo, backend):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    mark(ctx, "r1", "running", "inv1")
    backend.run_elsewhere("r1", "inv1", "failed", "failed")

    def broken(unit):
        raise testrun.LaunchError("the systemd user manager does not answer: boom")
    backend.unit_state = broken
    with pytest.raises(testrun.LaunchError, match="boom"):
        testrun.reconcile_service(ctx)
    assert backend.stopped == []
    assert testrun.read_record(ctx.policy, "r1")["status"] == "running"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_the_stale_branch_does_not_overwrite_a_cancelled_request(ctx, repo, backend, monkeypatch):
    pytest.importorskip("fcntl")
    register(ctx, repo)

    def cancel_then_report_changes(record):
        testrun.cancel_request(ctx, "r1")
        return ["tests/test_a.py"]
    monkeypatch.setattr(testrun, "stale_files", cancel_then_report_changes)
    view = testrun.run_request(ctx, "r1")
    assert view["status"] == "cancelled"
    assert testrun.read_record(ctx.policy, "r1")["status"] == "cancelled"


def test_a_concurrent_submission_of_one_id_never_overwrites_the_first(ctx, repo, monkeypatch):
    first = register(ctx, repo)
    real = testrun.read_record
    seen = []

    def blind_once(policy, request_id):
        seen.append(request_id)
        return None if len(seen) == 1 else real(policy, request_id)
    monkeypatch.setattr(testrun, "read_record", blind_once)
    with pytest.raises(testrun.LaunchError, match="different request"):
        register(ctx, repo, pytest_args=["-n0", "-k", "other"])
    monkeypatch.undo()
    assert testrun.read_record(ctx.policy, "r1") == first


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_two_nested_launchers_of_one_pending_id_execute_it_once(ctx, repo, backend, policy):
    pytest.importorskip("fcntl")
    marker = repo / "ran.txt"
    register(ctx, repo)
    record = testrun.read_record(policy, "r1")
    record["request"]["checks"] = [{"name": "pytest", "argv": [
        sys.executable, "-c", f"open({str(marker)!r}, 'a').write('x')"]}]
    testrun.write_record(policy, record)
    backend.inside = True
    backend.run_elsewhere("parent", "invP")
    stale_copy = testrun.read_record(policy, "r1")
    assert testrun._run_nested(ctx, stale_copy)["status"] == "passed"
    again = testrun._run_nested(ctx, dict(stale_copy))
    assert again["note"] == "not pending"
    assert marker.read_text() == "x"


def _classified(record_invocation, live_invocation):
    state = {"InvocationID": live_invocation, "Result": "success", "ExecMainCode": "1",
             "ExecMainStatus": "0"}
    record = {"invocation_id": record_invocation}
    report = {"complete": True, "checks": {"pytest": {"returncode": 0}}}
    unmet = testrun.unmet_conditions(state, record_invocation, report, ["pytest"], True)
    return testrun.classify(state, record, report, True, unmet)


@pytest.mark.parametrize("recorded, live", [("", "inv1"), (None, "inv1"), ("inv1", "inv2"),
                                            ("inv1", None)])
def test_an_empty_or_foreign_invocation_is_interrupted_never_failed_or_passed(recorded, live):
    assert _classified(recorded, live) == "interrupted"


def test_a_matching_invocation_still_passes():
    assert _classified("inv1", "inv1") == "passed"


class _StartFails(FakeBackend):
    def __init__(self, leave_unit):
        super().__init__()
        self.leave_unit = leave_unit

    def start(self, spec):
        if self.leave_unit:
            self.run_elsewhere("r1", "invZ")
        raise testrun.LaunchError("systemd-run could not start: timed out")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_start_that_failed_after_systemd_accepted_it_stays_active_for_reconcile(
        policy, repo, clock):
    pytest.importorskip("fcntl")
    backend = _StartFails(leave_unit=True)
    ctx = testrun.Context(policy, backend, clock=clock, sleep=clock.sleep, err=open(os.devnull, "w"))
    register(ctx, repo)
    record = testrun._start_locked(ctx, "r1", backend.slice_info(policy), 450)
    assert record["status"] == "running" and record["invocation_id"] == "invZ"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_start_that_failed_with_no_unit_is_an_infrastructure_failure(policy, repo, clock):
    pytest.importorskip("fcntl")
    backend = _StartFails(leave_unit=False)
    ctx = testrun.Context(policy, backend, clock=clock, sleep=clock.sleep, err=open(os.devnull, "w"))
    register(ctx, repo)
    record = testrun._start_locked(ctx, "r1", backend.slice_info(policy), 450)
    assert record["status"] == "infrastructure_failure"


def test_the_worst_case_of_one_run_call_including_every_lock_wait_stays_under_one_tool_call():
    assert testrun.DEFAULT_TIMEOUT <= testrun.MAX_TIMEOUT
    assert testrun.STOP_CALL == testrun.STOP_SETTLE + 5
    for timeout in (testrun.DEFAULT_TIMEOUT, testrun.MAX_TIMEOUT):
        worst = (testrun.DEFAULT_ADMISSION + testrun.START_LOCK_WAIT + timeout + testrun.GRACE
                 + testrun.STOP_LOCK_WAIT + testrun.STOP_CALL + testrun.STOP_SETTLE
                 + testrun.FINISH_LOCK_WAIT
                 + testrun.CLEANUP_TIMEOUT)
        assert worst == testrun.worst_case_seconds(timeout) < testrun.TOOL_CALL_LIMIT
    # Every control-lock wait inside a run is capped below the general limit.
    for cap in (testrun.START_LOCK_WAIT, testrun.STOP_LOCK_WAIT, testrun.FINISH_LOCK_WAIT):
        assert cap < testrun.CONTROL_WAIT
    assert testrun.SYSTEMD_RUN_TIMEOUT < testrun.MAX_TIMEOUT  # inside the execution window


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_control_lock_wait_never_passes_the_deadline_of_its_phase(ctx, repo, clock, policy):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    busy = hold(policy.control_lock)
    try:
        began = clock.now
        with pytest.raises(testrun.LaunchError, match="stayed busy for 5 s"):
            testrun.reconcile_service(ctx, deadline=clock.now + 5)
        assert clock.now - began < 6
        began = clock.now
        with pytest.raises(testrun.LaunchError):
            testrun.finish_request(ctx, "r1", deadline=clock.now + testrun.FINISH_LOCK_WAIT)
        assert clock.now - began <= testrun.FINISH_LOCK_WAIT + 1
        began = clock.now
        with pytest.raises(testrun.LaunchError):
            testrun._start_locked(ctx, "r1", {"cgroup": SLICE_CG}, 100,
                                  deadline=clock.now + testrun.START_LOCK_WAIT)
        assert clock.now - began <= testrun.START_LOCK_WAIT + 1
    finally:
        os.close(busy)


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_the_lock_wait_spends_the_admission_budget_the_reconcile_wait_shares(
        ctx, repo, backend, clock, policy):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    backend.run_elsewhere("other", "invX")
    view = testrun.run_request(ctx, "r1", admission_timeout=10)
    assert view["admitted"] is False
    assert clock.now - 1_000_000.0 < 12


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="file modes are POSIX")
def test_records_are_fsynced_and_a_state_directory_open_to_others_stops_the_write(
        ctx, repo, monkeypatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    register(ctx, repo)
    assert len(synced) >= 2  # the record's file, then its directory
    os.chmod(ctx.policy.state_dir, 0o755)
    with pytest.raises(testrun.LaunchError, match="mode 755"):
        register(ctx, repo, request_id="r2")


# --- containment decided from the process's own cgroup ----------------------------------------

def test_the_guard_decides_from_the_cgroup_file_alone_with_no_systemctl(tmp_path, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("systemctl must not be called")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    inside = _guard_host(tmp_path / "in", inside=True)
    outside = _guard_host(tmp_path / "out", inside=False)
    assert testcontrol.guard_message(**inside) is None
    assert "not allowed" in testcontrol.guard_message(**outside)


def test_the_slice_cgroup_is_derived_through_systemds_dash_hierarchy(tmp_path):
    policy = testcontrol.read_policy(_write_policy(tmp_path, uid=1234, slice="a-b-c.slice"))
    assert testcontrol.slice_cgroup(policy) == (
        "/user.slice/user-1234.slice/user@1234.service/a.slice/a-b.slice/a-b-c.slice")


@pytest.mark.parametrize("where", [
    "/user.slice/user-99999.slice/user@99999.service/wish.slice/wish-tests.slice/wish-tests-run.service",
    "/wish.slice/wish-tests.slice/wish-tests-run.service",
    SLICE_CG + "/other.service",
    SLICE_CG + "x/wish-tests-run.service",
])
def test_a_cgroup_outside_the_policys_service_path_is_not_inside_it(tmp_path, where):
    host = _guard_host(tmp_path, inside=True)
    pathlib.Path(host["proc_cgroup_file"]).write_text(f"0::{where}\n")
    assert "not allowed" in testcontrol.guard_message(**host)
    assert not testcontrol.inside_run_service(
        testcontrol.read_policy(host["policy_path"]), host["proc_cgroup_file"])


def test_a_policy_path_through_a_file_is_a_missing_policy(tmp_path):
    (tmp_path / "file").write_text("")
    with pytest.raises(testcontrol.PolicyMissing):
        testcontrol.read_policy(tmp_path / "file" / "policy.json")


# --- second review round -------------------------------------------------------------------------

def _nested_running(ctx, repo, backend, parent_alive=True):
    register(ctx, repo)
    record = testrun.read_record(ctx.policy, "r1")
    record.update(status="running", nested=True, parent_request="parent",
                  parent_invocation="invP", invocation_id=None)
    testrun.write_record(ctx.policy, record)
    if parent_alive:
        backend.run_elsewhere("parent", "invP")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_reconcile_and_cancel_leave_a_nested_record_alone_while_its_parent_runs(
        ctx, repo, backend):
    pytest.importorskip("fcntl")
    _nested_running(ctx, repo, backend)
    settled = testrun.reconcile_service(ctx)
    assert settled["state"] == "blocked" and settled["finalized"] == []
    assert testrun.read_record(ctx.policy, "r1")["status"] == "running"
    testrun.cancel_request(ctx, "r1")
    assert testrun.read_record(ctx.policy, "r1")["status"] == "running"
    assert backend.stopped == []
    backend.unit = {"LoadState": "not-found"}
    assert testrun.reconcile_service(ctx) == {"state": "free", "finalized": ["r1"]}
    assert testrun.read_record(ctx.policy, "r1")["status"] == "interrupted"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_nested_child_cannot_overwrite_a_record_reconcile_already_settled(
        ctx, repo, backend, policy, monkeypatch):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    backend.inside = True
    backend.run_elsewhere("parent", "invP")
    record = testrun.read_record(policy, "r1")
    record["request"]["checks"] = [{"name": "pytest", "argv": [sys.executable, "-c", "pass"]}]
    testrun.write_record(policy, record)

    def checks_while_the_parent_dies(rec, timeout, log):
        backend.unit = {"LoadState": "not-found"}
        testrun.reconcile_service(ctx)
        return {"pytest": {"returncode": 0, "elapsed": 0.1, "counts": {}, "tail": ""}}
    monkeypatch.setattr(testrun, "_checks_in_process", checks_while_the_parent_dies)
    view = testrun._run_nested(ctx, testrun.read_record(policy, "r1"))
    assert testrun.read_record(policy, "r1")["status"] == "interrupted"
    assert view["status"] == "interrupted"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_nested_record_names_its_parent_request_and_invocation(ctx, repo, backend, policy):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    record = testrun.read_record(policy, "r1")
    record["request"]["checks"] = [{"name": "pytest", "argv": [sys.executable, "-c", "pass"]}]
    testrun.write_record(policy, record)
    backend.inside = True
    backend.run_elsewhere("parent", "invP")
    claimed, _, view = testrun._claim_nested(ctx, "r1")
    assert view is None
    assert (claimed["parent_request"], claimed["parent_invocation"]) == ("parent", "invP")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_slice_at_another_cgroup_than_the_policys_starts_nothing(ctx, repo, backend):
    register(ctx, repo)
    backend.slice_info = lambda policy: {"cgroup": "/system.slice/wish-tests.slice",
                                         "memory_max": LIMIT, "swap_max": "0"}
    with pytest.raises(testrun.LaunchError, match="policy's path is /user.slice"):
        testrun.run_request(ctx, "r1")
    assert backend.started == []


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_nested_run_skips_the_slice_preflight(ctx, repo, backend, policy):
    register(ctx, repo)
    record = testrun.read_record(policy, "r1")
    record["request"]["checks"] = [{"name": "pytest", "argv": [sys.executable, "-c", "pass"]}]
    testrun.write_record(policy, record)
    backend.inside = True
    backend.run_elsewhere("parent", "invP")

    def forbidden(policy):
        raise AssertionError("no systemctl in a nested run")
    backend.slice_info = forbidden
    assert testrun.run_request(ctx, "r1")["status"] == "passed"


def test_a_state_directory_that_is_a_file_is_a_launch_error_and_json_on_the_command_line(
        policy, capsys, tmp_path):
    pathlib.Path(policy.state_dir).write_text("not a directory")
    with pytest.raises(testrun.LaunchError, match="is not a directory"):
        testrun.write_record(policy, {"id": "r1"})
    ctx = testrun.Context(policy, FakeBackend())
    assert testrun.main(["status", "r1"], ctx) == 2
    assert "error" in json.loads(capsys.readouterr().out)


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="file modes are POSIX")
def test_a_failing_temporary_file_or_link_is_a_launch_error(policy, monkeypatch):
    def no_space(*a, **kw):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(testrun.tempfile, "mkstemp", no_space)
    with pytest.raises(testrun.LaunchError, match="No space"):
        testrun.write_record(policy, {"id": "r1"})
    monkeypatch.undo()
    monkeypatch.setattr(os, "link", no_space)
    with pytest.raises(testrun.LaunchError, match="No space"):
        testrun.create_record(policy, {"id": "r2"})


@pytest.mark.parametrize("change, message", [
    ({"slice": "wish-tests"}, "slice must end in .slice"),
    ({"service": "wish-tests-run"}, "service must end in .service"),
])
def test_a_slice_or_service_without_its_unit_suffix_is_a_policy_error(tmp_path, change, message):
    with pytest.raises(testcontrol.PolicyError, match=message):
        testcontrol.read_policy(_write_policy(tmp_path, **change))


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_failed_start_with_a_job_still_creating_the_unit_stays_starting(policy, repo, clock):
    pytest.importorskip("fcntl")
    backend = _StartFails(leave_unit=False)
    backend.unit = {"LoadState": "not-found", "Job": "42"}
    ctx = testrun.Context(policy, backend, clock=clock, sleep=clock.sleep, err=open(os.devnull, "w"))
    register(ctx, repo)
    record = testrun._start_locked(ctx, "r1", backend.slice_info(policy), 450)
    assert record["status"] == "starting" and "timed out" in record["start_error"]


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_cancelled_run_records_what_the_unit_and_cgroup_held_before_the_stop(
        ctx, repo, backend):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    mark(ctx, "r1", "running", "invOLD")
    backend.run_elsewhere("r1", "invOLD")
    backend.unit.update(Result="success", ExecMainCode="0", ExecMainStatus="0", MainPID="77")
    outcome = testrun.cancel_request(ctx, "r1")
    result = outcome["record"]["result"]
    assert outcome["status"] == "cancelled"
    assert result["exit"] == {"Result": None, "ExecMainCode": None, "ExecMainStatus": None}
    assert result["before_stop"]["unit"]["Result"] == "success"
    assert result["before_stop"]["unit"]["MainPID"] == "77"
    assert result["memory_taken_before_stop"] is True
    assert result["memory_peak_bytes"] == 5000 and result["pytest_processes"] == 2


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_the_first_two_seconds_of_a_run_are_sampled_every_tenth_of_a_second(
        ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    state = {"n": 0}

    def react():
        state["n"] += 1
        if state["n"] == 40:
            write_report(testrun.read_record(ctx.policy, "r1"))
            backend.finish()
            clock.on_sleep = None
    clock.on_sleep = react
    testrun.run_request(ctx, "r1")
    polls = [d for d in clock.slept if d in (0.1, 1.0)]
    fast = polls.index(1.0)
    assert 19 <= fast <= 21 and polls[:fast] == [0.1] * fast and set(polls[fast:]) == {1.0}


class _KilledEarly(FakeBackend):
    """The run is OOM-killed before any sample sees the kill: the slice counted it,
    the run cgroup is gone."""

    def slice_events(self, cgroup):
        return {"oom": 0, "oom_kill": 1 if self.unit.get("Result") == "oom-kill" else 0}

    def sample(self, cgroup):
        return {"procs": [(1, "bash")], "peak": 3_000_000, "oom_group": "1", "events": {}}


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_run_counters_the_slice_contradicts_are_null_and_marked_not_observed(policy, repo, clock):
    pytest.importorskip("fcntl")
    backend = _KilledEarly()
    ctx = testrun.Context(policy, backend, clock=clock, sleep=clock.sleep, err=open(os.devnull, "w"))
    register(ctx, repo)

    def react():
        backend.finish(result="oom-kill", code="2", status="9")
        clock.on_sleep = None
    clock.on_sleep = react
    view = testrun.run_request(ctx, "r1")
    result = view["result"]
    assert result["oom_killed"] is True and result["oom"]["slice_oom_kill_delta"] == 1
    assert result["run_values_observed"] is False
    assert result["oom"]["oom"] is None and result["oom"]["oom_kill"] is None
    assert result["memory_peak_bytes"] is None and result["pytest_processes"] is None


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_killed_wrapper_with_no_report_is_interrupted_not_failed(ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    clock.on_sleep = lambda: backend.finish(result="signal", code="2", status="9")
    view = testrun.run_request(ctx, "r1")
    assert view["status"] == "interrupted"


def test_an_incomplete_report_is_interrupted_but_an_oom_kill_keeps_its_own_outcome():
    state = {"InvocationID": "i", "Result": "oom-kill", "ExecMainCode": "2", "ExecMainStatus": "9"}
    record = {"invocation_id": "i"}
    unmet = ["the wrapper did not finish its report"]
    assert testrun.classify(state, record, None, True, unmet) == "interrupted"
    assert testrun.classify(state, record, None, True, unmet, oom_killed=True) == "failed"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_timed_out_run_reports_the_last_forty_log_lines_as_its_failure_output(
        ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo)

    def write_log():
        record = testrun.read_record(ctx.policy, "r1")
        pathlib.Path(record["log"]).write_text("".join(f"line {n}\n" for n in range(1, 51)))
        clock.on_sleep = None
    clock.on_sleep = write_log
    view = testrun.run_request(ctx, "r1")
    lines = view["result"]["failure_output"].splitlines()
    assert view["status"] == "timed_out" and len(lines) == 40
    assert lines[0] == "line 11" and lines[-1] == "line 50"


# --- third review round --------------------------------------------------------------------------

def _hold_control_lock_between(clock, policy, start, end):
    """Hold the control lock while the fake clock is within [start, end)."""
    fcntl = pytest.importorskip("fcntl")
    state = {"fd": None}

    def react():
        inside = start <= clock.now < end
        if inside and state["fd"] is None:
            state["fd"] = os.open(policy.control_lock, os.O_RDWR)
            fcntl.flock(state["fd"], fcntl.LOCK_EX)
        elif not inside and state["fd"] is not None:
            os.close(state["fd"])
            state["fd"] = None
    clock.on_sleep = react
    return state


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_hard_stop_that_cannot_get_the_lock_is_retried_until_it_does(
        ctx, repo, backend, clock, policy):
    register(ctx, repo)
    hard_stop = clock.now + testrun.DEFAULT_TIMEOUT + testrun.GRACE
    state = _hold_control_lock_between(clock, policy, hard_stop - 1, hard_stop + 5)
    view = testrun.run_request(ctx, "r1")
    if state["fd"] is not None:
        os.close(state["fd"])
    assert backend.stopped == ["inv1"] and view["status"] == "timed_out"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_hard_stop_that_never_gets_the_lock_leaves_the_record_running_for_reconcile(
        ctx, repo, backend, clock, policy):
    register(ctx, repo)
    hard_stop = clock.now + testrun.DEFAULT_TIMEOUT + testrun.GRACE
    state = _hold_control_lock_between(clock, policy, hard_stop - 1, hard_stop + 1000)
    view = testrun.run_request(ctx, "r1")
    os.close(state["fd"])
    assert view["status"] == "infrastructure_failure" and "hard stop" in view["note"]
    assert backend.stopped == []
    assert testrun.read_record(policy, "r1")["status"] == "running"
    assert clock.now <= hard_stop + testrun.STOP_LOCK_WAIT + testrun.STOP_ATTEMPT_WAIT + 2


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_service_that_outlives_its_hard_stop_ends_the_wait_and_stays_for_reconcile(
        ctx, repo, backend, clock, policy):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    backend.stop = lambda unit: backend.stopped.append("inv1")  # the unit stays
    began = clock.now
    view = testrun.run_request(ctx, "r1")
    assert view["status"] == "infrastructure_failure" and "after the hard stop" in view["note"]
    assert testrun.read_record(policy, "r1")["status"] == "running"
    assert clock.now - began <= (testrun.DEFAULT_TIMEOUT + testrun.GRACE + testrun.STOP_SETTLE + 3)


def test_the_budget_counts_the_stop_call_and_the_wait_after_it_and_says_what_it_assumes():
    assert "no other launcher is reconciling" in testrun.worst_case_seconds.__doc__
    for name in (".claude/agents/test-runner.md", ".codex/agents/test-runner.toml"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert f"execution is up to {testrun.DEFAULT_TIMEOUT}" in text
        assert "no other launcher is reconciling" in text.replace("\n", " ")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_cancel_whose_before_stop_sample_read_nothing_does_not_mark_run_values_observed(
        ctx, repo, backend):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    mark(ctx, "r1", "running", "invOLD")
    backend.run_elsewhere("r1", "invOLD")
    backend.sample = lambda cgroup: {"procs": [], "peak": None, "oom_group": None, "events": {}}
    result = testrun.cancel_request(ctx, "r1")["record"]["result"]
    assert result["run_values_observed"] is False and result["memory_peak_bytes"] is None


@pytest.mark.parametrize("parent_request, parent_invocation", [
    (None, "invP"), ("parent", None), ("", "invP"), ("parent", "")])
def test_a_nested_record_without_both_parent_fields_is_never_taken_to_have_a_live_parent(
        parent_request, parent_invocation):
    record = {"nested": True, "parent_request": parent_request,
              "parent_invocation": parent_invocation}
    live = {"LoadState": "loaded", "ActiveState": "active", "SubState": "running",
            "Description": "wish-tests parent", "InvocationID": "invP", "Job": ""}
    assert testrun._nested_parent_alive(record, live) is False
    complete = dict(record, parent_request="parent", parent_invocation="invP")
    assert testrun._nested_parent_alive(complete, live) is True


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_cancelling_a_nested_record_names_the_parent_request_and_stops_nothing(
        ctx, repo, backend):
    pytest.importorskip("fcntl")
    _nested_running(ctx, repo, backend)
    outcome = testrun.cancel_request(ctx, "r1")
    assert "running request parent" in outcome["note"] and "nothing was stopped" in outcome["note"]
    assert outcome["stopped"] is False and backend.stopped == []


def test_output_without_a_final_newline_reaches_the_log_while_the_check_still_runs(
        tmp_path, repo):
    import threading
    import time
    flag, log = tmp_path / "flag", tmp_path / "out.log"
    script = ("import os, sys, time\n"
              "sys.stdout.write('partial'); sys.stdout.flush()\n"
              f"while not os.path.exists({str(flag)!r}): time.sleep(0.05)\n")
    record = {"request": {"workdir": str(repo), "checks": [
        {"name": "pytest", "argv": [sys.executable, "-c", script]}]}}
    done = {}
    thread = threading.Thread(target=lambda: done.update(
        testrun._checks_in_process(record, None, str(log))))
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not (log.exists() and "partial" in log.read_text()):
            time.sleep(0.05)
        seen = log.exists() and "partial" in log.read_text()
    finally:
        flag.write_text("")
        thread.join(10)
    assert seen and done["pytest"]["returncode"] == 0


@pytest.mark.parametrize("fields", [{}, {"parent_request": None, "parent_invocation": None},
                                    {"parent_request": "", "parent_invocation": ""}])
def test_two_empty_parent_fields_are_not_a_match_for_a_service_that_reports_none(fields):
    anonymous = {"LoadState": "loaded", "ActiveState": "active", "SubState": "running", "Job": ""}
    assert testrun._nested_parent_alive({"nested": True, **fields}, anonymous) is False


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock and uids are Linux/macOS")
def test_a_hard_stop_that_fails_at_once_is_retried_at_the_paced_interval_not_in_a_spin(
        ctx, repo, backend, clock):
    pytest.importorskip("fcntl")
    register(ctx, repo)
    attempts = []

    def failing_stop(unit):
        attempts.append(clock.now)
        assert len(attempts) < 500, "the hard stop is being retried in a spin"
        raise testrun.LaunchError("the systemd user manager is not usable: boom")
    backend.stop = failing_stop
    view = testrun.run_request(ctx, "r1")
    assert view["status"] == "infrastructure_failure"
    gaps = [b - a for a, b in zip(attempts, attempts[1:])]
    assert len(attempts) > 5 and min(gaps) >= ctx.fast_poll - 1e-9


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="flock is Linux/macOS")
def test_a_clock_that_never_stops_failing_a_loop_raises_instead_of_hanging():
    clock = Clock()
    with pytest.raises(AssertionError, match="looping forever"):
        while True:
            clock.sleep(1)


def test_a_nested_cancel_note_without_a_recorded_parent_does_not_print_none(
        ctx, repo, backend, monkeypatch):
    pytest.importorskip("fcntl")
    _nested_running(ctx, repo, backend)
    monkeypatch.setattr(testrun, "_nested_parent_alive", lambda record, live: True)
    record = testrun.read_record(ctx.policy, "r1")
    record["parent_request"] = None
    testrun.write_record(ctx.policy, record)
    note = testrun.cancel_request(ctx, "r1")["note"]
    assert "None" not in note and "nothing was stopped" in note


def test_submit_and_status_print_the_absolute_path_of_the_record(ctx, repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    argv = ["submit", "--id", "r1", "--session", "s1", "--workdir", str(repo),
            "--no-ruff", "--no-genui", "--", "-n0", "tests/test_a.py"]
    assert testrun.main(argv, ctx) == 0
    submitted = json.loads(capsys.readouterr().out)
    expected = str((pathlib.Path(ctx.policy.state_dir) / "r1.json").resolve())
    assert submitted["record"] == expected and pathlib.Path(expected).is_absolute()
    assert submitted["id"] == "r1" and submitted["status"] == "pending"
    assert testrun.main(["status", "r1"], ctx) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["record"] == expected and shown["status"] == "pending"
    assert pathlib.Path(shown["record"]).is_file()
