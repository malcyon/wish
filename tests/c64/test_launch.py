"""Checks `tools/c64/launch.sh` and the old-name `tools/c64/porlaunch.sh` against stub programs on PATH."""
from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX launcher")

C64 = pathlib.Path(__file__).resolve().parents[2] / "tools" / "c64"
ENTRY_POINTS = ["launch.sh", "porlaunch.sh"]

FLATPAK = """#!/bin/sh
{
  echo "pid=$$"
  echo "display=$DISPLAY"
  echo "por_display=$POR_DISPLAY"
  echo "por_headless=$POR_HEADLESS"
  echo "por_slot=$POR_SLOT"
  echo "por_vicerc=$POR_VICERC"
  for a in "$@"; do echo "arg=$a"; done
} > "$STUB_RECORD"
exec sleep 60
"""
XVFB = "#!/bin/sh\nexec sleep 60\n"
XDOTOOL = "#!/bin/sh\nexit 0\n"


@pytest.fixture
def stubs(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("flatpak", FLATPAK), ("Xvfb", XVFB), ("xdotool", XDOTOOL)):
        path = bindir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    record = tmp_path / "record.txt"
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
           "STUB_RECORD": str(record), "POR_HEADLESS": "1", "POR_DISPLAY": ":97",
           "POR_SLOT": "3", "POR_VICERC": str(tmp_path / "vicerc"),
           "MONFLAGS": "-binarymonitor -binarymonitoraddress 127.0.0.1:6599",
           "PORFLAGS": "-extra"}
    return env, record


def _launch(script, env, disk="DISK.D64"):
    args = [str(C64 / script)] + ([disk] if disk else [])
    return subprocess.Popen(args, env=env, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _recorded(record, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if record.exists() and record.read_text().endswith("\n") \
                and "arg=DISK.D64" in record.read_text():
            return dict_and_args(record.read_text())
        time.sleep(0.05)
    raise AssertionError("the stub flatpak never recorded a launch")


def dict_and_args(text):
    fields, args = {}, []
    for line in text.splitlines():
        key, _, value = line.partition("=")
        (args.append(value) if key == "arg" else fields.__setitem__(key, value))
    return fields, args


def _stop(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def _group_members(pgid):
    out = subprocess.run(["ps", "-o", "pid=", "-g", str(pgid)],
                         capture_output=True, text=True)
    return out.stdout.split()


@pytest.mark.parametrize("script", ENTRY_POINTS)
def test_the_emulator_runs_under_the_callers_pid_with_the_slots_environment(stubs, script):
    env, record = stubs
    proc = _launch(script, env)
    try:
        fields, args = _recorded(record)
        assert int(fields["pid"]) == proc.pid
        assert fields["display"] == ":97" and fields["por_slot"] == "3"
        assert args[:2] == ["run", "--die-with-parent"]
        assert "-config" in args and "+sound" in args and "-extra" in args
        assert "-binarymonitoraddress" in args and "127.0.0.1:6599" in args
        assert args[-2:] == ["-autostart", "DISK.D64"]
    finally:
        _stop(proc)


def test_both_names_pass_the_same_arguments(stubs, tmp_path):
    env, record = stubs
    seen = []
    for script in ENTRY_POINTS:
        record.unlink(missing_ok=True)
        proc = _launch(script, env)
        try:
            seen.append(_recorded(record)[1])
        finally:
            _stop(proc)
    assert seen[0] == seen[1]


@pytest.mark.parametrize("script", ENTRY_POINTS)
def test_a_group_terminate_ends_the_launch_and_its_display(stubs, script):
    env, record = stubs
    proc = _launch(script, env)
    _recorded(record)
    assert len(_group_members(proc.pid)) >= 2          # the emulator and the display
    os.killpg(proc.pid, signal.SIGTERM)
    assert proc.wait(timeout=15) == -signal.SIGTERM
    end = time.time() + 5
    while time.time() < end and _group_members(proc.pid):
        time.sleep(0.05)
    assert _group_members(proc.pid) == []


def test_a_missing_disk_is_refused_alike_and_starts_nothing(stubs):
    env, record = stubs
    codes = []
    for script in ENTRY_POINTS:
        proc = _launch(script, env, disk=None)
        codes.append(proc.wait(timeout=15))
        assert not record.exists()
    assert codes[0] != 0 and codes[0] == codes[1]


def test_the_old_name_is_only_an_exec_of_the_new_one():
    lines = [ln for ln in (C64 / "porlaunch.sh").read_text().splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert lines == ['exec "$(dirname -- "${BASH_SOURCE[0]}")/launch.sh" "$@"']
    if sys.platform != "win32":
        assert os.access(C64 / "porlaunch.sh", os.X_OK)
