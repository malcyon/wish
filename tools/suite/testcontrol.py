"""The managed-host test policy and the checks that a process runs inside its cgroup.

`/etc/wish/test-runner.json` is written by the host's configuration management
and read here. When it is present and enabled, `tests/conftest.py` stops any
pytest that is not inside the fixed run service under the memory-limited slice.
Nothing in this module reads an environment variable to find the policy or to
skip a check: the only switch is the policy file.

Importable on every platform: only the standard library is used at import time,
and the Linux-only parts return "not managed" elsewhere.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from dataclasses import dataclass

POLICY_PATH = "/etc/wish/test-runner.json"
SCHEMA_VERSION = 1
CGROUP_ROOT = "/sys/fs/cgroup"
PROC_CGROUP = "/proc/self/cgroup"

#: What a stopped pytest tells the caller to run instead.
LAUNCHER_COMMAND = ("submit it with `.venv/bin/python tools/suite/testrun.py "
                    "submit --requester ADDRESS --workdir DIR --file PATH ... "
                    "-- PYTEST_ARGS`, then give the request ID and record path "
                    "to the session's test-runner, which runs it")

#: What the whole-suite diagnostic tells an uncontained caller to run instead.
SUITERUN_COMMAND = ("submit it with `.venv/bin/python tools/suite/testrun.py "
                    "submit --suiterun [suiterun arguments]`, then give the "
                    "request ID and record path to the session's test-runner, "
                    "which runs it")


class PolicyError(Exception):
    """The policy file is there and unusable, or the host cannot meet it."""


class PolicyMissing(PolicyError):
    """There is no policy file: the host is not managed."""


@dataclass(frozen=True)
class Policy:
    schema_version: int
    enabled: bool
    uid: int
    slice: str
    service: str
    execution_lock: str
    control_lock: str
    state_dir: str
    memory_max_bytes: int
    allowed_environment: tuple[str, ...]


_KEYS: dict[str, type] = {
    "schema_version": int, "enabled": bool, "uid": int, "slice": str,
    "service": str, "execution_lock": str, "control_lock": str,
    "state_dir": str, "memory_max_bytes": int, "allowed_environment": list,
}


def read_policy(path: str | pathlib.Path = POLICY_PATH) -> Policy:
    """The parsed policy; `PolicyMissing` when absent, `PolicyError` when wrong."""
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        raise PolicyMissing(f"{path} does not exist") from None
    except (OSError, UnicodeDecodeError) as err:
        raise PolicyError(f"{path} cannot be read: {err}") from None
    try:
        data = json.loads(text)
    except ValueError as err:
        raise PolicyError(f"{path} is not valid JSON: {err}") from None
    if not isinstance(data, dict):
        raise PolicyError(f"{path} must hold a JSON object")
    version = data.get("schema_version")
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise PolicyError(f"{path} has schema_version {version!r}; "
                          f"this launcher understands {SCHEMA_VERSION}")
    for key, kind in _KEYS.items():
        if key not in data:
            raise PolicyError(f"{path} is missing the key {key}")
        value = data[key]
        if kind is int and isinstance(value, bool) or not isinstance(value, kind):
            raise PolicyError(f"{path}: {key} must be {kind.__name__}, "
                              f"not {type(value).__name__}")
    for key in ("slice", "service", "execution_lock", "control_lock", "state_dir"):
        if not data[key]:
            raise PolicyError(f"{path}: {key} is empty")
    for key, suffix in (("slice", ".slice"), ("service", ".service")):
        if not data[key].endswith(suffix):
            raise PolicyError(f"{path}: {key} must end in {suffix}")
    if data["memory_max_bytes"] <= 0:
        raise PolicyError(f"{path}: memory_max_bytes must be positive")
    names = data["allowed_environment"]
    if not all(isinstance(n, str) and n for n in names):
        raise PolicyError(f"{path}: allowed_environment must list names")
    return Policy(
        schema_version=data["schema_version"], enabled=data["enabled"],
        uid=data["uid"], slice=data["slice"], service=data["service"],
        execution_lock=data["execution_lock"], control_lock=data["control_lock"],
        state_dir=data["state_dir"], memory_max_bytes=data["memory_max_bytes"],
        allowed_environment=tuple(names))


def parse_proc_cgroup(text: str) -> str | None:
    """The cgroup v2 path in `/proc/<pid>/cgroup` text, or None without one."""
    for line in text.splitlines():
        if line.startswith("0::"):
            return line[3:].removesuffix(" (deleted)").rstrip("/") or "/"
    return None


def is_within(path: str | None, base: str) -> bool:
    """Whether `path` is `base` or a descendant cgroup of it."""
    if not path:
        return False
    base = base.rstrip("/")
    return path.rstrip("/") == base or path.startswith(base + "/")


def run_cgroup(slice_cgroup: str, policy: Policy) -> str:
    return slice_cgroup.rstrip("/") + "/" + policy.service


def check_membership(policy: Policy, proc_cgroup_text: str, slice_cgroup: str) -> bool:
    """Whether the process whose `/proc/.../cgroup` text this is runs inside the
    fixed run service beneath the slice, descendant cgroups included."""
    return is_within(parse_proc_cgroup(proc_cgroup_text), run_cgroup(slice_cgroup, policy))


def read_memory_max(slice_cgroup: str, cgroup_root: str = CGROUP_ROOT) -> int | None:
    """The slice's `memory.max` in bytes; None when it is `max` or unreadable."""
    try:
        text = (pathlib.Path(cgroup_root) / slice_cgroup.lstrip("/")
                / "memory.max").read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(text) if text.isdigit() else None


def check_limit(policy: Policy, slice_cgroup: str, cgroup_root: str = CGROUP_ROOT) -> str | None:
    """None when the slice's memory.max is the policy's; otherwise what is wrong."""
    actual = read_memory_max(slice_cgroup, cgroup_root)
    if actual == policy.memory_max_bytes:
        return None
    shown = "not readable or not set" if actual is None else str(actual)
    return (f"{policy.slice} has memory.max {shown}, "
            f"but the policy requires {policy.memory_max_bytes}")


def slice_cgroup(policy: Policy) -> str:
    """The slice's cgroup path in the policy user's manager, derived from its name.

    systemd nests a dashed slice name under its prefixes (`wish-tests.slice` lives
    in `wish.slice`), and the user manager sits under the user's own slice. Reading
    it from the name needs no `systemctl`, which a contained child with a scrubbed
    environment cannot reach.
    """
    stem = policy.slice.removesuffix(".slice")
    parts = stem.split("-")
    nested = ["-".join(parts[:i + 1]) + ".slice" for i in range(len(parts))]
    return (f"/user.slice/user-{policy.uid}.slice/user@{policy.uid}.service/"
            + "/".join(nested))


_POPEN = re.compile(r"^(\d+\*)?popen(//.*)?$")


def remote_xdist(specs) -> list[str]:
    """The `--tx` specs that would leave the managed cgroup (ssh, socket, ...)."""
    return [s for s in specs or () if not _POPEN.match(str(s).strip())]


def guard_message(policy_path: str | pathlib.Path = POLICY_PATH, *,
                  platform: str | None = None,
                  proc_cgroup_file: str | pathlib.Path = PROC_CGROUP,
                  cgroup_root: str = CGROUP_ROOT, tx=(), command: str = LAUNCHER_COMMAND) -> str | None:
    """Why this process may not run pytest, or None when it may.

    A host without the policy, or with it disabled, and every non-Linux
    platform, have no restriction. The environment is never consulted, so
    `CI=1`, an xdist worker marker or a request ID cannot lift it.
    """
    if not (platform or sys.platform).startswith("linux"):
        return None
    try:
        policy = read_policy(policy_path)
    except PolicyMissing:
        return None
    except PolicyError as err:
        return f"The managed test policy is unusable ({err}); no test command ran."
    if not policy.enabled:
        return None
    use = f"Run it through the launcher: {command}."
    slice_cg = slice_cgroup(policy)
    try:
        proc = pathlib.Path(proc_cgroup_file).read_text(encoding="utf-8")
    except OSError as err:
        return f"Direct pytest is not allowed here (own cgroup unreadable: {err}). {use}"
    if not check_membership(policy, proc, slice_cg):
        return (f"Direct pytest is not allowed on this host: it must run inside "
                f"{policy.service} beneath {policy.slice}. {use}")
    wrong = check_limit(policy, slice_cg, cgroup_root)
    if wrong:
        return f"Test containment is not in force: {wrong}. No test command ran."
    remote = remote_xdist(tx)
    if remote:
        return (f"Remote xdist ({', '.join(remote)}) would leave {policy.slice}; "
                "use local workers only.")
    return None


def inside_run_service(policy: Policy,
                       proc_cgroup_file: str | pathlib.Path = PROC_CGROUP) -> bool:
    """Whether this process already runs inside the fixed run service, which
    makes a nested launcher call part of that request rather than a new one."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        proc = pathlib.Path(proc_cgroup_file).read_text(encoding="utf-8")
    except OSError:
        return False
    return check_membership(policy, proc, slice_cgroup(policy))
