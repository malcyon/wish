"""A VICE that has exited must stop `launch()` and `boot()` at once.

The emulator opens its monitor ports early and can exit seconds later -- an
autostart it cannot open, say -- so `launch()` connected in that window and
`boot()` then waited its whole 120 s for a prompt on a dead process.  No
emulator is needed: the process is a fake whose `poll()` says it has exited.
"""

import pytest
from conftest import load_tools_module

session = load_tools_module("session")

LOG = ("AUTOSTART: Error - Cannot open /tmp/wish/instance/0/SIDE1.D64\n"
       "Error - Failed to autostart\n")


class ExitedProc:
    pid = 999999
    returncode = 1

    def poll(self):
        return self.returncode


class FakeMon:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _session(tmp_path):
    sess = session.Session()
    sess.here = str(tmp_path)
    (tmp_path / "vice.log").write_text(LOG)
    return sess


def _no_waiting(monkeypatch):
    def refuse(seconds):
        raise AssertionError("slept instead of stopping")
    monkeypatch.setattr(session.time, "sleep", refuse)


def test_launch_raises_with_the_log_when_vice_has_already_exited(
        tmp_path, monkeypatch):
    sess = _session(tmp_path)

    def popen(args, stdout=None, **kw):
        stdout.write(LOG.encode())      # what the dying VICE wrote into vice.log
        stdout.flush()
        return ExitedProc()

    monkeypatch.setattr(session.subprocess, "Popen", popen)
    monkeypatch.setattr(session.os, "getpgid", lambda pid: pid, raising=False)
    # The monitor answers, as it did in the window before VICE exited.
    monkeypatch.setattr(sess, "mon", lambda timeout=3.0: FakeMon())
    monkeypatch.setattr(session.time, "sleep", lambda s: None)
    monkeypatch.setattr(sess, "log", lambda *a: None)

    with pytest.raises(RuntimeError, match="Cannot open /tmp/wish/instance/0/SIDE1.D64"):
        sess.launch()


def test_boot_raises_at_once_when_vice_exits_after_launch_returned(
        tmp_path, monkeypatch):
    sess = _session(tmp_path)
    monkeypatch.setattr(sess, "launch", lambda: setattr(sess, "_proc", ExitedProc()))
    monkeypatch.setattr(sess, "screen", lambda: None)
    monkeypatch.setattr(sess, "log", lambda *a: None)
    _no_waiting(monkeypatch)

    with pytest.raises(RuntimeError, match="VICE exited with status 1"):
        sess.boot()


def test_a_running_vice_is_left_alone(tmp_path, monkeypatch):
    sess = _session(tmp_path)

    class Running:
        def poll(self):
            return None

    sess._proc = Running()
    sess._require_alive()          # must not raise
