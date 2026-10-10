#!/usr/bin/env python3
"""Run local test commands one at a time, inside the memory-limited systemd service.

    tools/suite/testrun.py submit --requester ADDR --workdir DIR [--file PATH ...]
                           [--no-ruff] [--no-genui] [--timeout SEC] [--id ID]
                           [--memory-max BYTES] [--session S] -- PYTEST_ARGS...
    tools/suite/testrun.py submit --suiterun [suiterun arguments]
    tools/suite/testrun.py run ID [--admission-timeout SEC] [--budget SEC]
    tools/suite/testrun.py status ID | list [--session S] [--active] | cancel ID | reconcile

Each subcommand prints one JSON object. `submit` records a request (commit,
file fingerprints, exact argv, allowed environment); `run` takes the
execution lock, reconciles the fixed service, starts the request as
`wish-tests-run.service` under `wish-tests.slice`, waits, and records the
result. The host policy (`tools/suite/testcontrol.py`) names every path and
limit. Nothing here falls back to running a test outside the service.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import datetime
import hashlib
import json
import os
import pathlib
import re
import secrets
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.registry import scratch  # noqa: E402
from tools.suite import testcontrol  # noqa: E402

TERMINAL = frozenset({"passed", "failed", "timed_out", "cancelled", "interrupted",
                      "stale", "infrastructure_failure"})
ACTIVE = frozenset({"starting", "running"})

#: Budgets (seconds) that add up under the 600 s a single tool call may take.
DEFAULT_ADMISSION = 60
DEFAULT_TIMEOUT = 480
MAX_TIMEOUT = 500
CLEANUP_TIMEOUT = 30
#: A whole-suite diagnostic runs longer than one tool call; `run` waits in stages.
SUITERUN_TIMEOUT = 3600
SUITERUN_MAX_TIMEOUT = 7200
DEFAULT_BUDGET = 480
#: Seconds the launcher waits beyond systemd's own runtime limit before stopping.
GRACE = 20
CONTROL_WAIT = 45
POLL = 1.0
MIN_MEMORY_MAX = 16 * 1024 * 1024

DESCRIPTION = "wish-tests {}"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
DESCRIPTION_PATTERN = re.compile(r"^wish-tests (\S+)$")
COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected|warnings?)")


class LaunchError(Exception):
    """A condition that stops a command before it changes anything."""


# --- records ---------------------------------------------------------------

def _record_file(policy: testcontrol.Policy, request_id: str) -> pathlib.Path:
    if not ID_PATTERN.match(request_id):
        raise LaunchError(f"{request_id!r} is not a valid request ID "
                          "(letters, digits, dot, dash, underscore; at most 80)")
    return pathlib.Path(policy.state_dir) / f"{request_id}.json"


def read_record(policy: testcontrol.Policy, request_id: str) -> dict | None:
    path = _record_file(policy, request_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        raise LaunchError(f"record {path} is unreadable: {err}") from None


def write_record(policy: testcontrol.Policy, record: dict) -> None:
    """Atomic replace in the state directory, mode 0600."""
    directory = pathlib.Path(policy.state_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(record, out, indent=1, sort_keys=True)
            out.write("\n")
        os.replace(temporary, _record_file(policy, record["id"]))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def all_records(policy: testcontrol.Policy) -> list[dict]:
    directory = pathlib.Path(policy.state_dir)
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("."):
            continue
        with contextlib.suppress(OSError, ValueError):
            found.append(json.loads(path.read_text(encoding="utf-8")))
    return found


# --- the systemd and cgroup layer -------------------------------------------

UNIT_PROPERTIES = ("LoadState", "ActiveState", "SubState", "Result", "ExecMainCode",
                   "ExecMainStatus", "InvocationID", "Description", "ControlGroup",
                   "Job", "MainPID")


def _parse_properties(text: str) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            found[key] = value
    return found


class SystemBackend:
    """The real user manager and cgroup filesystem. Tests substitute a fake."""

    def __init__(self, cgroup_root: str = testcontrol.CGROUP_ROOT):
        self.cgroup_root = pathlib.Path(cgroup_root)

    def _systemctl(self, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(["systemctl", "--user", *args], capture_output=True,
                                  text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as err:
            raise LaunchError(f"the systemd user manager is not usable: {err}") from None

    def _cg_file(self, cgroup: str, name: str) -> pathlib.Path:
        return self.cgroup_root / cgroup.lstrip("/") / name

    def read_cgroup_file(self, cgroup: str, name: str) -> str | None:
        try:
            return self._cg_file(cgroup, name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def slice_info(self, policy: testcontrol.Policy) -> dict:
        shown = self._systemctl("show", policy.slice, "-p", "LoadState", "-p",
                                "ActiveState", "-p", "ControlGroup")
        if shown.returncode != 0:
            raise LaunchError("the systemd user manager does not answer: "
                              + (shown.stderr.strip() or "no output"))
        props = _parse_properties(shown.stdout)
        if props.get("LoadState") != "loaded":
            raise LaunchError(f"{policy.slice} is not loaded in the user manager "
                              f"(LoadState={props.get('LoadState')})")
        if props.get("ActiveState") != "active" or not props.get("ControlGroup"):
            started = self._systemctl("start", policy.slice)
            if started.returncode != 0:
                raise LaunchError(f"{policy.slice} could not be started: "
                                  + started.stderr.strip())
            props = _parse_properties(self._systemctl(
                "show", policy.slice, "-p", "ControlGroup").stdout)
        cgroup = props.get("ControlGroup", "")
        if not cgroup.startswith("/"):
            raise LaunchError(f"{policy.slice} has no cgroup")
        memory_max = testcontrol.read_memory_max(cgroup, str(self.cgroup_root))
        swap = self.read_cgroup_file(cgroup, "memory.swap.max")
        return {"cgroup": cgroup, "memory_max": memory_max,
                "swap_max": swap.strip() if swap is not None else None}

    def slice_events(self, cgroup: str) -> dict[str, int]:
        return _events(self.read_cgroup_file(cgroup, "memory.events"))

    def unit_state(self, unit: str) -> dict[str, str]:
        args = ["show", unit]
        for name in UNIT_PROPERTIES:
            args += ["-p", name]
        done = self._systemctl(*args)
        if done.returncode != 0:
            raise LaunchError("the systemd user manager does not answer: "
                              + (done.stderr.strip() or "no output"))
        return _parse_properties(done.stdout)

    def start(self, spec: dict) -> str:
        argv = ["systemd-run", "--user", f"--unit={spec['unit']}",
                f"--slice={spec['slice']}", f"--description={spec['description']}",
                "--remain-after-exit", "--expand-environment=no",
                f"--working-directory={spec['workdir']}"]
        for name, value in spec["env"].items():
            argv.append(f"--setenv={name}={value}")
        properties = {"Type": "exec", "ExitType": "main", "KillMode": "control-group",
                      "OOMPolicy": "kill", "Restart": "no",
                      "RuntimeMaxSec": str(int(spec["runtime_max"])),
                      "TimeoutStopSec": "15s", "SendSIGKILL": "yes",
                      "MemorySwapMax": "0", "StandardInput": "null",
                      "StandardOutput": f"append:{spec['log']}",
                      "StandardError": "inherit"}
        if spec.get("memory_max"):
            properties["MemoryMax"] = str(int(spec["memory_max"]))
        for name, value in properties.items():
            argv += ["-p", f"{name}={value}"]
        argv += ["--", *spec["argv"]]
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as err:
            raise LaunchError(f"systemd-run could not start: {err}") from None
        if done.returncode != 0:
            raise LaunchError("systemd-run failed: "
                              + ((done.stderr or done.stdout).strip() or f"exit {done.returncode}"))
        found = re.search(r"invocation ID: ([0-9a-f]{32})", done.stderr + done.stdout)
        if found:
            return found.group(1)
        state = self.unit_state(spec["unit"])
        if not state.get("InvocationID"):
            raise LaunchError("the service started but reported no invocation ID")
        return state["InvocationID"]

    def stop(self, unit: str) -> None:
        self._systemctl("stop", unit, timeout=90)

    def reset_failed(self, unit: str) -> None:
        self._systemctl("reset-failed", unit)

    def cgroup_exists(self, cgroup: str) -> bool:
        return self._cg_file(cgroup, "").is_dir()

    def cgroup_populated(self, cgroup: str) -> bool | None:
        text = self.read_cgroup_file(cgroup, "cgroup.events")
        if text is None:
            return None
        return _events(text).get("populated", 1) != 0

    def sample(self, cgroup: str) -> dict:
        procs = []
        text = self.read_cgroup_file(cgroup, "cgroup.procs") or ""
        for line in text.split():
            try:
                comm = pathlib.Path(f"/proc/{line}/comm").read_text().strip()
            except OSError:
                continue
            procs.append((int(line), comm))
        peak = self.read_cgroup_file(cgroup, "memory.peak")
        group = self.read_cgroup_file(cgroup, "memory.oom.group")
        return {"procs": procs,
                "peak": int(peak) if peak and peak.strip().isdigit() else None,
                "oom_group": group.strip() if group else None,
                "events": _events(self.read_cgroup_file(cgroup, "memory.events"))}

    def inside_service(self, policy: testcontrol.Policy) -> bool:
        return testcontrol.inside_run_service(policy)


def _events(text: str | None) -> dict[str, int]:
    found = {}
    for line in (text or "").splitlines():
        key, _, value = line.partition(" ")
        if value.strip().isdigit():
            found[key] = int(value)
    return found


# --- context and locks --------------------------------------------------------

@dataclasses.dataclass
class Context:
    policy: testcontrol.Policy
    backend: object
    clock: object = time.time
    sleep: object = time.sleep
    err: object = None
    cleanup_timeout: float = CLEANUP_TIMEOUT
    poll: float = POLL

    def say(self, line: str) -> None:
        print(line, file=self.err or sys.stderr, flush=True)


def _open_lock(path: str) -> int:
    try:
        return os.open(path, os.O_RDWR)
    except OSError as err:
        raise LaunchError(f"lock file {path} cannot be opened ({err}); the host "
                          "provisions it and this launcher never creates it") from None


def _try_flock(fd: int) -> bool:
    import fcntl  # Linux only; imported here so the module loads elsewhere
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def acquire(ctx: Context, path: str, timeout: float, on_wait=None) -> int | None:
    """An exclusive flock on the existing file `path`; None when `timeout` passes."""
    fd = _open_lock(path)
    deadline = ctx.clock() + timeout
    waited = False
    while True:
        if _try_flock(fd):
            return fd
        if ctx.clock() >= deadline:
            os.close(fd)
            return None
        if not waited and on_wait:
            on_wait()
            waited = True
        ctx.sleep(0.25)


@contextlib.contextmanager
def control_lock(ctx: Context):
    fd = acquire(ctx, ctx.policy.control_lock, CONTROL_WAIT)
    if fd is None:
        raise LaunchError(f"the control lock {ctx.policy.control_lock} stayed busy "
                          f"for {CONTROL_WAIT} s")
    try:
        yield
    finally:
        os.close(fd)


def _iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat(
        timespec="seconds")


# --- registering a request -----------------------------------------------------

def _git(workdir: str, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", workdir, *args], capture_output=True,
                              timeout=120)
    except (OSError, subprocess.SubprocessError) as err:
        raise LaunchError(f"git could not run in {workdir}: {err}") from None


def head_sha(workdir: str) -> str:
    done = _git(workdir, "rev-parse", "HEAD")
    if done.returncode != 0:
        raise LaunchError(f"{workdir} is not a git checkout with a commit")
    return done.stdout.decode().strip()


def dirty_paths(workdir: str) -> list[str]:
    done = _git(workdir, "status", "--porcelain", "-z", "--untracked-files=all")
    if done.returncode != 0:
        raise LaunchError(f"git status failed in {workdir}")
    paths = []
    entries = done.stdout.decode("utf-8", "replace").split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":  # the next field is the old name
            index += 1
    return sorted(set(paths))


def _expand(workdir: pathlib.Path, path: str) -> list[str]:
    """`path` as relative names; a directory becomes the files git knows in it."""
    target = workdir / path
    if target.is_dir():
        listed = _git(str(workdir), "ls-files", "-z", "--cached", "--others",
                      "--exclude-standard", "--", path)
        return [p for p in listed.stdout.decode("utf-8", "replace").split("\0") if p]
    return [path]


def fingerprint(workdir: str, paths) -> dict[str, str]:
    """sha256 of each file's bytes, `missing` for one that is absent."""
    root = pathlib.Path(workdir)
    found = {}
    for given in paths:
        for name in _expand(root, given):
            target = root / name
            if target.is_file():
                found[name] = hashlib.sha256(target.read_bytes()).hexdigest()
            else:
                found[name] = "missing"
    return dict(sorted(found.items()))


def _python_for(workdir: str) -> str:
    candidate = pathlib.Path(workdir) / ".venv" / "bin" / "python"
    return str(candidate) if candidate.is_file() else sys.executable


def _selection_paths(workdir: str, pytest_args) -> list[str]:
    paths = []
    for arg in pytest_args:
        if arg.startswith("-"):
            continue
        name = arg.split("::", 1)[0]
        if name and (pathlib.Path(workdir) / name).exists():
            paths.append(name)
    return paths


def build_checks(workdir: str, pytest_args, ruff: bool, genui: bool) -> list[dict]:
    python = _python_for(workdir)
    checks = [{"name": "pytest", "argv": [python, "-m", "pytest", *pytest_args]}]
    if ruff:
        ruff_bin = pathlib.Path(workdir) / ".venv" / "bin" / "ruff"
        argv = [str(ruff_bin)] if ruff_bin.is_file() else [python, "-m", "ruff"]
        checks.append({"name": "ruff", "argv": [*argv, "check", "."]})
    if genui:
        checks.append({"name": "genui",
                       "argv": [python, "tools/generate/genui.py", "--check"]})
    return checks


def register_request(ctx: Context, *, request_id: str | None, session: str,
                     requester: str, workdir: str, files=(), pytest_args=(),
                     ruff: bool = True, genui: bool = True, timeout: int | None = None,
                     memory_max: int | None = None, suiterun_args=None,
                     environ=None) -> tuple[dict, bool]:
    """Record a request. Returns `(record, created)`; an identical resubmission
    returns the existing record, different content under the same ID is an error."""
    policy = ctx.policy
    kind = "suiterun" if suiterun_args is not None else "pytest"
    request_id = request_id or (time.strftime("%Y%m%dT%H%M%S", time.gmtime(ctx.clock()))
                                + "-" + secrets.token_hex(3))
    _record_file(policy, request_id)
    top = pathlib.Path(workdir).resolve()
    if not top.is_dir():
        raise LaunchError(f"working directory {workdir} does not exist")
    workdir = str(top)
    cap = SUITERUN_MAX_TIMEOUT if kind == "suiterun" else MAX_TIMEOUT
    timeout = timeout or (SUITERUN_TIMEOUT if kind == "suiterun" else DEFAULT_TIMEOUT)
    if timeout <= 0 or timeout > cap:
        raise LaunchError(f"--timeout {timeout} is outside 1..{cap} seconds"
                          + ("" if kind == "suiterun" else
                             "; the admission, execution and cleanup budgets must "
                             "fit one 600 s tool call"))
    if memory_max is not None and not MIN_MEMORY_MAX <= memory_max < policy.memory_max_bytes:
        raise LaunchError(f"--memory-max {memory_max} must be at least {MIN_MEMORY_MAX} "
                          f"and below the slice limit {policy.memory_max_bytes}")
    environ = os.environ if environ is None else environ
    env = {k: environ[k] for k in policy.allowed_environment if k in environ}
    if kind == "suiterun":
        python = _python_for(str(REPO))
        checks = [{"name": "suiterun", "argv": [python, str(REPO / "tools/suite/suiterun.py"),
                                                *suiterun_args]}]
        relevant = list(files)
        pytest_args = []
    else:
        checks = build_checks(workdir, list(pytest_args), ruff, genui)
        relevant = [*files, *_selection_paths(workdir, pytest_args)]
    dirty = dirty_paths(workdir)
    if not files and kind == "pytest":
        # No declared list: the changed and untracked files are the relevant ones.
        relevant += dirty
    request = {
        "session": session, "requester": requester, "workdir": workdir,
        "head": head_sha(workdir), "kind": kind,
        "files": fingerprint(workdir, relevant),
        "checks": checks, "pytest_args": list(pytest_args),
        "ruff": bool(ruff) and kind == "pytest", "genui": bool(genui) and kind == "pytest",
        "timeout": timeout, "memory_max": memory_max, "env": env,
    }
    existing = read_record(policy, request_id)
    if existing is not None:
        if existing["request"] != request:
            raise LaunchError(f"request ID {request_id} already holds a different request")
        return existing, False
    record = {"schema": 1, "id": request_id, "request": request,
              "submitted": _iso(ctx.clock()), "status": "pending", "dirty": dirty,
              "invocation_id": None, "cancel_requested": False}
    if kind == "suiterun":
        record["note"] = ("A whole-suite diagnostic outlasts one 600 s tool call: call "
                          "`run ID` again to keep waiting; it re-attaches to the "
                          "running service and never starts it twice.")
    write_record(policy, record)
    return record, True


# --- status, results ------------------------------------------------------------

def read_status(ctx: Context, request_id: str) -> dict:
    record = read_record(ctx.policy, request_id)
    if record is None:
        raise LaunchError(f"no request {request_id}")
    return {"id": request_id, "status": record["status"], "record": record}


def list_requests(ctx: Context, session: str | None = None, active_only: bool = False) -> dict:
    rows = []
    for record in all_records(ctx.policy):
        if session and record["request"]["session"] != session:
            continue
        if active_only and record["status"] in TERMINAL:
            continue
        rows.append({"id": record["id"], "status": record["status"],
                     "session": record["request"]["session"],
                     "requester": record["request"]["requester"],
                     "submitted": record["submitted"]})
    return {"requests": rows}


def unit_busy(state: dict) -> bool:
    """A loaded service that is starting, running or stopping blocks the next request."""
    if state.get("LoadState") == "not-found":
        return bool(state.get("Job"))
    active, sub = state.get("ActiveState"), state.get("SubState")
    if state.get("Job"):
        return True
    if active in ("failed", "inactive"):
        return False
    return not (active == "active" and sub == "exited")


def unit_finished(state: dict) -> bool:
    return not unit_busy(state) and state.get("LoadState") != "not-found"


def unit_request(state: dict) -> str | None:
    found = DESCRIPTION_PATTERN.match(state.get("Description", ""))
    return found.group(1) if found else None


def parse_counts(text: str) -> dict[str, int]:
    """Counts from the last pytest summary line in `text`."""
    for line in reversed(text.splitlines()):
        if re.search(r"\bin [\d.]+s\b", line) and COUNT.search(line):
            counts = {}
            for number, word in COUNT.findall(line):
                counts[word.rstrip("s") if word.startswith("warning") else word] = int(number)
            return counts
    return {}


def unmet_conditions(state: dict, invocation_id: str | None, checks_doc: dict | None,
                     requested: list[str], cleanup_ok: bool) -> list[str]:
    """What stops a run from counting as passed; empty means it passed."""
    unmet = []
    if not invocation_id or state.get("InvocationID") != invocation_id:
        unmet.append("the service's invocation is not the recorded one")
    if state.get("Result") != "success":
        unmet.append(f"service Result is {state.get('Result')!r}, not 'success'")
    if state.get("ExecMainCode") != "1":
        unmet.append(f"ExecMainCode is {state.get('ExecMainCode')!r}, not 1 (exited)")
    if state.get("ExecMainStatus") != "0":
        unmet.append(f"ExecMainStatus is {state.get('ExecMainStatus')!r}, not 0")
    done = (checks_doc or {}).get("checks", {})
    for name in requested:
        found = done.get(name)
        if found is None:
            unmet.append(f"check {name} did not report")
        elif found.get("returncode") != 0:
            unmet.append(f"check {name} exited {found.get('returncode')}")
    if not (checks_doc or {}).get("complete"):
        unmet.append("the wrapper did not finish its report")
    if not cleanup_ok:
        unmet.append("cleanup did not complete")
    return unmet


def classify(state: dict, record: dict, checks_doc: dict | None, cleanup_ok: bool,
             unmet: list[str]) -> str:
    if not cleanup_ok:
        return "infrastructure_failure"
    if record.get("cancel_requested"):
        return "cancelled"
    if state.get("Result") == "timeout" or record.get("timeout_enforced"):
        return "timed_out"
    if not state.get("Result") or state.get("ExecMainCode") in (None, "", "0"):
        return "interrupted"
    return "passed" if not unmet else "failed"


def _read_json(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _unload(ctx: Context, run_cgroup: str, state: dict) -> tuple[bool, str]:
    """Stop and unload the fixed service, then wait for its cgroup to be gone or
    empty with no pending job. `(complete, detail)`."""
    unit = ctx.policy.service
    deadline = ctx.clock() + ctx.cleanup_timeout
    if state.get("LoadState") != "not-found":
        ctx.backend.stop(unit)
        ctx.backend.reset_failed(unit)
    while True:
        now = ctx.backend.unit_state(unit)
        gone = now.get("LoadState") == "not-found" and not now.get("Job")
        exists = ctx.backend.cgroup_exists(run_cgroup)
        empty = (not exists) or ctx.backend.cgroup_populated(run_cgroup) is False
        if gone and empty:
            return True, "service unloaded; cgroup gone or empty"
        if ctx.clock() >= deadline:
            return False, (f"after {ctx.cleanup_timeout:g} s: LoadState="
                           f"{now.get('LoadState')} ActiveState={now.get('ActiveState')} "
                           f"Job={now.get('Job')!r} cgroup_exists={exists} empty={empty}")
        if not gone:
            ctx.backend.stop(unit)
            ctx.backend.reset_failed(unit)
        ctx.sleep(0.25)


def _finish_locked(ctx: Context, record: dict, samples: dict | None = None,
                   unload: bool = True) -> dict:
    """Finalise `record` from the service and its report. Caller holds the control lock."""
    if record["status"] in TERMINAL:
        return record
    policy = ctx.policy
    request = record["request"]
    unit = policy.service
    samples = samples or {}
    try:
        live = ctx.backend.unit_state(unit)
    except LaunchError as err:
        live = {"LoadState": "not-found", "_error": str(err)}
    mine = (live.get("LoadState") != "not-found"
            and unit_request(live) == record["id"]
            and record.get("invocation_id") in (None, live.get("InvocationID")))
    if mine and unit_busy(live):
        raise LaunchError(f"{record['id']} is still running; it cannot be finalised")
    # Without a matching, finished service there is no completion evidence.
    state = live if mine else {}
    result: dict = {"unit": unit, "invocation_id": record.get("invocation_id"),
                    "tree_dirty": bool(record.get("dirty")),
                    "effective": {"pytest_args": request["pytest_args"],
                                  "PYTEST_ADDOPTS": request["env"].get("PYTEST_ADDOPTS")},
                    "log": record.get("log")}
    if not mine:
        result["reason"] = ("the service does not hold this request"
                            + (f" ({live['_error']})" if live.get("_error") else ""))
    now = ctx.clock()
    checks_doc = _read_json(record.get("checks_file"))
    run_cg = samples.get("run_cgroup") or record.get("run_cgroup") or ""
    exit_info = {k: state.get(k) for k in ("Result", "ExecMainCode", "ExecMainStatus")}
    if not run_cg:
        cleanup_ok, detail = True, "no cgroup path"
    elif unload and (mine or live.get("LoadState") == "not-found"):
        cleanup_ok, detail = _unload(ctx, run_cg, live)
    else:
        cleanup_ok, detail = True, "the service belongs to another request; left alone"
    requested = [c["name"] for c in request["checks"]]
    unmet = unmet_conditions(state, record.get("invocation_id"), checks_doc,
                             requested, cleanup_ok)
    status = classify(state, record, checks_doc, cleanup_ok, unmet)
    mem = (checks_doc or {}).get("memory") or {}
    events = samples.get("events") or {}
    before = record.get("slice_events_before") or {}
    after = samples.get("slice_events_after") or (
        ctx.backend.slice_events(run_cg.rsplit("/", 1)[0]) if run_cg else {})
    ran = (checks_doc or {}).get("checks", {})
    pytest_out = ran.get("pytest", {})
    changed = [name for name, digest in
               fingerprint(request["workdir"], list(request["files"])).items()
               if request["files"].get(name) != digest]
    result.update({
        "exit": exit_info,
        "elapsed_seconds": round(now - record["started_epoch"], 1)
        if record.get("started_epoch") else None,
        "pytest_processes": samples.get("max_processes"),
        "memory_peak_bytes": max(filter(None, [samples.get("peak"), mem.get("peak")]),
                                 default=None),
        "oom": {"oom": max(events.get("oom", 0), mem.get("oom", 0)),
                "oom_kill": max(events.get("oom_kill", 0), mem.get("oom_kill", 0)),
                "slice_oom_delta": after.get("oom", 0) - before.get("oom", 0),
                "slice_oom_kill_delta": after.get("oom_kill", 0) - before.get("oom_kill", 0),
                "memory_oom_group": samples.get("oom_group")},
        "counts": pytest_out.get("counts", {}),
        "checks": {n: {"returncode": c.get("returncode"), "elapsed": c.get("elapsed")}
                   for n, c in ran.items()},
        "checks_not_run": [n for n in requested if n not in ran],
        "failure_output": next((c.get("tail") for c in ran.values()
                                if c.get("returncode") != 0), None),
        "cleanup": {"complete": cleanup_ok, "detail": detail},
        "oom_killed": (state.get("Result") == "oom-kill"
                       or after.get("oom_kill", 0) > before.get("oom_kill", 0)),
        "conditions_unmet": unmet,
        "files_changed_during_run": changed,
        "valid_as_acceptance": status == "passed" and not changed,
    })
    record.update(status=status, finished=_iso(now), result=result)
    write_record(policy, record)
    return record


def finish_request(ctx: Context, request_id: str, samples: dict | None = None) -> dict:
    with control_lock(ctx):
        record = read_record(ctx.policy, request_id)
        if record is None:
            raise LaunchError(f"no request {request_id}")
        return _finish_locked(ctx, record, samples)


# --- reconcile and cancel ---------------------------------------------------------

def _reconcile_locked(ctx: Context) -> dict:
    policy = ctx.policy
    state = ctx.backend.unit_state(policy.service)
    holder = unit_request(state)
    finalized = []

    def settle_others(keep: str | None) -> None:
        for record in all_records(policy):
            if record["status"] in ACTIVE and record["id"] != keep:
                finished = _finish_locked(ctx, read_record(policy, record["id"]))
                finalized.append(finished["id"])

    if state.get("LoadState") == "not-found" and not state.get("Job"):
        settle_others(None)
        return {"state": "free", "finalized": finalized}
    if unit_busy(state):
        settle_others(holder)
        return {"state": "blocked", "request": holder, "unit": state,
                "finalized": finalized}
    record = read_record(policy, holder) if holder else None
    if record is not None and record["status"] in ACTIVE:
        _finish_locked(ctx, record)
        finalized.append(holder)
    else:
        slice_info = ctx.backend.slice_info(policy)
        ok, detail = _unload(ctx, slice_info["cgroup"] + "/" + policy.service, state)
        if not ok:
            return {"state": "blocked", "request": holder, "detail": detail,
                    "finalized": finalized}
    after = ctx.backend.unit_state(policy.service)
    if after.get("LoadState") != "not-found" or after.get("Job"):
        return {"state": "blocked", "request": holder, "unit": after,
                "finalized": finalized}
    settle_others(None)
    return {"state": "free", "finalized": finalized}


def reconcile_service(ctx: Context) -> dict:
    """Make the fixed service free for the next request without stopping a healthy
    run: a busy service blocks, a finished one is finalised and unloaded, and a
    record left active with no service becomes `interrupted`."""
    with control_lock(ctx):
        return _reconcile_locked(ctx)


def cancel_request(ctx: Context, request_id: str) -> dict:
    """Cancel a pending request, or stop the service only when it still runs this
    request's invocation."""
    policy = ctx.policy
    with control_lock(ctx):
        record = read_record(policy, request_id)
        if record is None:
            raise LaunchError(f"no request {request_id}")
        if record["status"] in TERMINAL:
            return {"id": request_id, "status": record["status"], "stopped": False,
                    "record": record}
        if record["status"] == "pending":
            record.update(status="cancelled", finished=_iso(ctx.clock()),
                          result={"reason": "cancelled before it started"})
            write_record(policy, record)
            return {"id": request_id, "status": "cancelled", "stopped": False,
                    "record": record}
        state = ctx.backend.unit_state(policy.service)
        mine = (state.get("LoadState") != "not-found"
                and unit_request(state) == request_id
                and record.get("invocation_id") in (None, state.get("InvocationID")))
        if not mine:
            record = _finish_locked(ctx, record)
            return {"id": request_id, "status": record["status"], "stopped": False,
                    "record": record,
                    "note": "the service is not running this request; nothing was stopped"}
        record["cancel_requested"] = True
        write_record(policy, record)
        ctx.backend.stop(policy.service)
        record = _finish_locked(ctx, record)
        return {"id": request_id, "status": record["status"], "stopped": True,
                "record": record}


# --- running ----------------------------------------------------------------------

def _preflight(ctx: Context, memory_max: int | None) -> dict:
    policy = ctx.policy
    if hasattr(os, "getuid") and os.getuid() != policy.uid:
        raise LaunchError(f"the policy permits UID {policy.uid}, not {os.getuid()}")
    info = ctx.backend.slice_info(policy)
    if info["memory_max"] != policy.memory_max_bytes:
        raise LaunchError(f"{policy.slice} has memory.max {info['memory_max']}, but the "
                          f"policy requires {policy.memory_max_bytes}; nothing started")
    if info.get("swap_max") not in (None, "0"):
        raise LaunchError(f"{policy.slice} has memory.swap.max {info['swap_max']}, "
                          "not 0; nothing started")
    return info


def _result_view(record: dict, **extra) -> dict:
    view = {"id": record["id"], "status": record["status"],
            "result": record.get("result"), "record": record}
    view.update(extra)
    return view


def stale_files(record: dict) -> list[str]:
    request = record["request"]
    changed = [name for name, digest in fingerprint(
        request["workdir"], list(request["files"])).items()
        if request["files"].get(name) != digest]
    try:
        if head_sha(request["workdir"]) != request["head"]:
            changed.append("HEAD")
    except LaunchError:
        changed.append("HEAD")
    return changed


def _service_spec(ctx: Context, record: dict, log: str, checks_file: str) -> dict:
    request = record["request"]
    return {"unit": ctx.policy.service, "slice": ctx.policy.slice,
            "description": DESCRIPTION.format(record["id"]),
            "workdir": request["workdir"], "env": request["env"],
            "runtime_max": request["timeout"], "memory_max": request.get("memory_max"),
            "log": log,
            "argv": [sys.executable, str(pathlib.Path(__file__).resolve()), "_wrap",
                     str(_record_file(ctx.policy, record["id"]))]}


def _start_locked(ctx: Context, request_id: str, slice_info: dict, timeout: int) -> dict | None:
    """Persist `starting`, create the service, capture its invocation. None when the
    request is no longer pending."""
    policy = ctx.policy
    with control_lock(ctx):
        record = read_record(policy, request_id)
        if record is None or record["status"] != "pending":
            return record
        scratch_dir = scratch.ensure(scratch.scratch_dir("testrun"))
        log = str(scratch_dir / f"{request_id}.log")
        checks_file = str(scratch_dir / f"{request_id}.checks.json")
        for path in (log, checks_file):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
        now = ctx.clock()
        run_cg = slice_info["cgroup"].rstrip("/") + "/" + policy.service
        record.update(status="starting", started=_iso(now), started_epoch=now,
                      deadline_epoch=now + timeout, log=log, checks_file=checks_file,
                      run_cgroup=run_cg,
                      slice_events_before=ctx.backend.slice_events(slice_info["cgroup"]))
        write_record(policy, record)
        try:
            invocation = ctx.backend.start(_service_spec(ctx, record, log, checks_file))
        except LaunchError as err:
            record.update(status="infrastructure_failure", finished=_iso(ctx.clock()),
                          result={"reason": f"the service did not start: {err}"})
            write_record(policy, record)
            return record
        record.update(status="running", invocation_id=invocation,
                      unit=policy.service)
        write_record(policy, record)
        return record


def _wait(ctx: Context, record: dict, slice_info: dict, budget_end: float | None) -> tuple[dict, bool]:
    """Wait for the service; sample memory and processes. Returns `(samples,
    finished)`; the service is stopped when systemd's own limit and the grace pass."""
    policy = ctx.policy
    samples: dict = {"run_cgroup": record["run_cgroup"], "max_processes": 0,
                     "peak": None, "events": {}}
    hard_stop = record["deadline_epoch"] + GRACE
    stopped = False
    while True:
        state = ctx.backend.unit_state(policy.service)
        if state.get("LoadState") == "not-found" or unit_request(state) != record["id"]:
            break
        if unit_finished(state):
            break
        got = ctx.backend.sample(record["run_cgroup"])
        python = [p for p in got["procs"] if p[1].startswith("python")]
        samples["max_processes"] = max(samples["max_processes"], max(len(python) - 1, 0))
        if got["peak"]:
            samples["peak"] = max(samples["peak"] or 0, got["peak"])
        if got["events"]:
            samples["events"] = got["events"]
        samples["oom_group"] = got["oom_group"] or samples.get("oom_group")
        now = ctx.clock()
        if now >= hard_stop and not stopped:
            stopped = True
            with control_lock(ctx):
                current = read_record(policy, record["id"])
                if current and current["status"] == "running":
                    current["timeout_enforced"] = True
                    write_record(policy, current)
                    live = ctx.backend.unit_state(policy.service)
                    if live.get("InvocationID") == current.get("invocation_id"):
                        ctx.backend.stop(policy.service)
            continue
        if budget_end is not None and now >= budget_end:
            return samples, False
        ctx.sleep(ctx.poll)
    samples["slice_events_after"] = ctx.backend.slice_events(slice_info["cgroup"])
    return samples, True


def _checks_in_process(record: dict, timeout: float | None, log: str | None) -> dict:
    """Run the requested checks one after another in this process's cgroup."""
    request = record["request"]
    done = {}
    began = time.monotonic()
    out = open(log, "a", encoding="utf-8") if log else None
    try:
        for check in request["checks"]:
            started = time.monotonic()
            remaining = None if timeout is None else timeout - (started - began)
            if remaining is not None and remaining <= 0:
                done[check["name"]] = {"returncode": 124, "elapsed": 0.0,
                                       "tail": "the request's deadline had passed"}
                continue
            tail = collections.deque(maxlen=60)
            try:
                proc = subprocess.Popen(check["argv"], cwd=request["workdir"],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, errors="replace")
            except OSError as err:
                done[check["name"]] = {"returncode": 127, "elapsed": 0.0, "tail": str(err)}
                continue
            timer = None
            if remaining is not None:
                import threading
                timer = threading.Timer(remaining, proc.kill)
                timer.start()
            for line in proc.stdout:
                tail.append(line)
                if out:
                    out.write(line)
                    out.flush()
                else:
                    sys.stdout.write(line)
                    sys.stdout.flush()
            code = proc.wait()
            if timer:
                timer.cancel()
            text = "".join(tail)
            done[check["name"]] = {"returncode": code,
                                   "elapsed": round(time.monotonic() - started, 1),
                                   "counts": parse_counts(text) if check["name"] == "pytest" else {},
                                   "tail": text[-2000:] if code else ""}
    finally:
        if out:
            out.close()
    return done


def _run_nested(ctx: Context, record: dict) -> dict:
    """Run inside the parent request's service: no new service and no lock."""
    policy = ctx.policy
    state = ctx.backend.unit_state(policy.service)
    parent = next((r for r in all_records(policy)
                   if r["status"] == "running"
                   and r.get("invocation_id") == state.get("InvocationID")), None)
    timeout = float(record["request"]["timeout"])
    if parent is not None:
        timeout = min(timeout, parent["deadline_epoch"] - ctx.clock() - 5)
    if timeout <= 0:
        record.update(status="timed_out", finished=_iso(ctx.clock()),
                      result={"reason": "the parent request has no time left"})
        write_record(policy, record)
        return _result_view(record, nested=True)
    scratch_dir = scratch.ensure(scratch.scratch_dir("testrun"))
    log = str(scratch_dir / f"{record['id']}.log")
    record.update(status="running", started=_iso(ctx.clock()), log=log, nested=True,
                  started_epoch=ctx.clock())
    write_record(policy, record)
    done = _checks_in_process(record, timeout, log)
    bad = [n for n, c in done.items() if c["returncode"] != 0]
    timed_out = any(c["returncode"] in (124, -9) for c in done.values())
    record.update(status="passed" if not bad else ("timed_out" if timed_out else "failed"),
                  finished=_iso(ctx.clock()),
                  result={"nested": True, "checks": {n: {"returncode": c["returncode"],
                                                       "elapsed": c["elapsed"]}
                                                   for n, c in done.items()},
                          "counts": done.get("pytest", {}).get("counts", {}),
                          "failure_output": next((c["tail"] for c in done.values()
                                                  if c["returncode"] != 0), None),
                          "log": log, "tree_dirty": bool(record.get("dirty"))})
    write_record(policy, record)
    return _result_view(record, nested=True)


def run_request(ctx: Context, request_id: str, *, admission_timeout: float = DEFAULT_ADMISSION,
                budget: float | None = None) -> dict:
    policy = ctx.policy
    record = read_record(policy, request_id)
    if record is None:
        raise LaunchError(f"no request {request_id}")
    if record["status"] in TERMINAL:
        return _result_view(record, note="already finished; a request never reruns")
    if record["status"] == "starting":
        raise LaunchError(f"{request_id} is starting in another launcher; run "
                          "`reconcile` if that launcher has died")
    info = _preflight(ctx, record["request"].get("memory_max"))
    if ctx.backend.inside_service(policy):
        if record["status"] != "pending":
            return _result_view(record, note="not pending")
        return _run_nested(ctx, record)
    if record["status"] == "running":
        return _attach(ctx, record, info, budget)
    held = acquire(ctx, policy.execution_lock, admission_timeout,
                   on_wait=lambda: ctx.say(
                       f"Waiting for the test execution lock for up to "
                       f"{admission_timeout:g} s (another run is active)."))
    if held is None:
        return _result_view(record, admitted=False,
                            note=f"admission timed out after {admission_timeout:g} s; "
                                 "the request is still pending")
    try:
        deadline = ctx.clock() + admission_timeout
        while True:
            settled = reconcile_service(ctx)
            if settled["state"] == "free":
                break
            if ctx.clock() >= deadline:
                return _result_view(record, admitted=False, blocked_by=settled.get("request"),
                                    note="the fixed service is busy; the request is still pending")
            ctx.sleep(ctx.poll)
        record = read_record(policy, request_id)
        if record["status"] != "pending":
            return _result_view(record, note="no longer pending")
        changed = stale_files(record)
        if changed:
            with control_lock(ctx):
                record = read_record(policy, request_id)
                record.update(status="stale", finished=_iso(ctx.clock()),
                              result={"reason": "requested files changed before the start; "
                                                "nothing ran", "changed": changed})
                write_record(policy, record)
            return _result_view(record)
        timeout = record["request"]["timeout"]
        record = _start_locked(ctx, request_id, info, timeout)
        if record is None or record["status"] != "running":
            return _result_view(record)
        return _attach(ctx, record, info, budget)
    finally:
        os.close(held)


def _attach(ctx: Context, record: dict, info: dict, budget: float | None) -> dict:
    """Wait for the running service; finalise when it ends."""
    if record["request"]["kind"] == "suiterun":
        budget = DEFAULT_BUDGET if budget is None else budget
    budget_end = None if budget is None else ctx.clock() + budget
    samples, finished = _wait(ctx, record, info, budget_end)
    if not finished:
        current = read_record(ctx.policy, record["id"])
        return _result_view(current, note="still running; call `run ID` again to keep waiting")
    record = finish_request(ctx, record["id"], samples)
    return _result_view(record)


# --- the wrapper that runs inside the service -----------------------------------------

def _own_memory() -> dict:
    try:
        path = testcontrol.parse_proc_cgroup(pathlib.Path("/proc/self/cgroup").read_text())
        base = pathlib.Path(testcontrol.CGROUP_ROOT) / (path or "").lstrip("/")
        peak = (base / "memory.peak").read_text().strip()
        events = _events((base / "memory.events").read_text())
        return {"peak": int(peak) if peak.isdigit() else None,
                "oom": events.get("oom", 0), "oom_kill": events.get("oom_kill", 0)}
    except OSError:
        return {}


def wrap(record_path: str) -> int:
    """ExecStart of the service: every requested check runs, the report is written
    after each one, and the exit status is nonzero if any failed."""
    record = json.loads(pathlib.Path(record_path).read_text(encoding="utf-8"))
    target = pathlib.Path(record["checks_file"])
    report: dict = {"id": record["id"], "complete": False, "checks": {}}

    def save() -> None:
        report["memory"] = _own_memory()
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(json.dumps(report, indent=1), encoding="utf-8")
        os.replace(temporary, target)

    for check in record["request"]["checks"]:
        one = dict(record)
        one["request"] = dict(record["request"], checks=[check])
        report["checks"].update(_checks_in_process(one, None, None))
        save()
    report["complete"] = True
    save()
    return 0 if all(c["returncode"] == 0 for c in report["checks"].values()) else 1


# --- command line --------------------------------------------------------------------

def _emit(obj: dict) -> None:
    print(json.dumps(obj, indent=1, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit", help="register a request")
    submit.add_argument("--requester", default="unspecified")
    submit.add_argument("--workdir", default=".")
    submit.add_argument("--file", action="append", default=[])
    submit.add_argument("--no-ruff", action="store_true")
    submit.add_argument("--no-genui", action="store_true")
    submit.add_argument("--timeout", type=int)
    submit.add_argument("--id")
    submit.add_argument("--memory-max", type=int)
    submit.add_argument("--session")
    submit.add_argument("--suiterun", action="store_true",
                        help="register a whole-suite diagnostic; the rest of the "
                             "line is passed to suiterun.py")
    submit.add_argument("pytest_args", nargs="*")
    run = sub.add_parser("run", help="run a registered request in the service")
    run.add_argument("id")
    run.add_argument("--admission-timeout", type=float, default=DEFAULT_ADMISSION)
    run.add_argument("--budget", type=float,
                     help="seconds to wait before leaving a whole-suite run going")
    status = sub.add_parser("status")
    status.add_argument("id")
    listing = sub.add_parser("list")
    listing.add_argument("--session")
    listing.add_argument("--active", action="store_true")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("id")
    sub.add_parser("reconcile")
    wrapper = sub.add_parser("_wrap", help=argparse.SUPPRESS)
    wrapper.add_argument("record")
    return parser


def _split_suiterun(argv: list[str]) -> tuple[list[str], list[str] | None]:
    if argv and argv[0] == "submit" and "--suiterun" in argv:
        at = argv.index("--suiterun")
        return argv[:at + 1], argv[at + 1:]
    return argv, None


def main(argv=None, ctx: Context | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    head, suiterun_args = _split_suiterun(argv)
    args = _build_parser().parse_args(head)
    if args.command == "_wrap":
        return wrap(args.record)
    try:
        if ctx is None:
            ctx = Context(testcontrol.read_policy(), SystemBackend())
        if args.command == "submit":
            session = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID")
            if not session:
                raise LaunchError("no session: set CLAUDE_CODE_SESSION_ID or pass --session")
            record, created = register_request(
                ctx, request_id=args.id, session=session, requester=args.requester,
                workdir=args.workdir, files=args.file, pytest_args=args.pytest_args,
                ruff=not args.no_ruff, genui=not args.no_genui, timeout=args.timeout,
                memory_max=args.memory_max, suiterun_args=suiterun_args)
            _emit({"id": record["id"], "status": record["status"], "record": record,
                   "created": created})
            return 0
        if args.command == "run":
            view = run_request(ctx, args.id, admission_timeout=args.admission_timeout,
                               budget=args.budget)
            _emit(view)
            if view["status"] == "passed":
                return 0
            return 3 if view["status"] in ("pending", "running") else 1
        if args.command == "status":
            _emit(read_status(ctx, args.id))
        elif args.command == "list":
            _emit(list_requests(ctx, args.session, args.active))
        elif args.command == "cancel":
            _emit(cancel_request(ctx, args.id))
        elif args.command == "reconcile":
            settled = reconcile_service(ctx)
            _emit(settled)
            return 0 if settled["state"] == "free" else 3
    except (LaunchError, testcontrol.PolicyError) as err:
        _emit({"error": str(err)})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
