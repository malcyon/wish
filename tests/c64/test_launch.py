"""Checks `tools/c64/launch.sh` against stub programs on PATH."""
from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX launcher")

C64 = pathlib.Path(__file__).resolve().parents[2] / "tools" / "c64"
SCRIPT = "launch.sh"

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
XEPHYR = """#!/bin/sh
for a in "$@"; do echo "arg=$a"; done > "$STUB_XEPHYR"
exec sleep 60
"""
XDOTOOL = "#!/bin/sh\nexit 0\n"


@pytest.fixture
def stubs(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("flatpak", FLATPAK), ("Xvfb", XVFB), ("Xephyr", XEPHYR),
                       ("xdotool", XDOTOOL)):
        path = bindir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    record = tmp_path / "record.txt"
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
           "STUB_RECORD": str(record),
           "STUB_XEPHYR": str(tmp_path / "xephyr.txt"), "POR_HEADLESS": "1", "POR_DISPLAY": ":97",
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


def _vice_command(env, sound):
    return (["run", "--die-with-parent", "--share=network", "--env=DISPLAY=:97",
             "--command=x64sc", "net.sf.VICE", "-config", env["POR_VICERC"],
             "-speed", "100", "-VICIIshowstatusbar", "-VICIIfilter", "0",
             "-VICIIaspectmode", "2", "-VICIIglfilter", "1",
             "-binarymonitor", "-binarymonitoraddress", "127.0.0.1:6599"]
            + (["+sound"] if sound else []) + ["-extra", "-autostart", "DISK.D64"])


def test_the_emulator_runs_under_the_callers_pid_with_the_slots_environment(stubs):
    env, record = stubs
    proc = _launch(SCRIPT, env)
    try:
        fields, args = _recorded(record)
        assert int(fields["pid"]) == proc.pid
        assert fields["display"] == ":97" and fields["por_slot"] == "3"
        assert args == _vice_command(env, sound=True)
    finally:
        _stop(proc)


def test_a_visible_launch_opens_a_titled_resizeable_display_and_stays_silent(
        stubs, tmp_path):
    env, record = stubs
    env = {**env, "POR_HEADLESS": "0"}
    proc = _launch(SCRIPT, env)
    try:
        _, args = _recorded(record)
        assert args == _vice_command(env, sound=False)
        xephyr = tmp_path / "xephyr.txt"
        end = time.time() + 10
        while time.time() < end and not xephyr.exists():
            time.sleep(0.05)
        assert xephyr.read_text().splitlines() == [
            "arg=:97", "arg=-screen", "arg=1400x1050", "arg=-resizeable",
            "arg=-title", "arg=PoR (slot 3)"]
    finally:
        _stop(proc)


def test_a_group_terminate_ends_the_launch_and_its_display(stubs):
    env, record = stubs
    proc = _launch(SCRIPT, env)
    _recorded(record)
    assert len(_group_members(proc.pid)) >= 2          # the emulator and the display
    os.killpg(proc.pid, signal.SIGTERM)
    assert proc.wait(timeout=15) == -signal.SIGTERM
    end = time.time() + 5
    while time.time() < end and _group_members(proc.pid):
        time.sleep(0.05)
    assert _group_members(proc.pid) == []


def test_a_missing_disk_is_refused_and_starts_nothing(stubs):
    env, record = stubs
    proc = _launch(SCRIPT, env, disk=None)
    assert proc.wait(timeout=15) != 0
    assert not record.exists()


