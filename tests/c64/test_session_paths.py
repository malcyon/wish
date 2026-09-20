"""`Session`'s base class built its disk and log paths with an f-string and a
hardcoded `/`, which is a Windows separator mismatch -- the same bug Windows
CI caught in `tools/secret_of_the_silver_blades/ssbwarp.py` and `tools/curse_of_the_azure_bonds/curserun.py` (#539), which this
project's own review then found still live in the shared base class both
those subclasses inherit from (#546 (tools/c64/session.py's Session base class
still builds disk/log paths with a hardcoded forward slash, the same bug
Windows CI just caught in its subclasses)).

**Comparing the produced path against a string built with the same hardcoded
`/` proves nothing on this (POSIX) machine.** `os.sep` is `/` here too, so
`f"{here}/SIDE1.D64"` and `os.path.join(here, "SIDE1.D64")` come out
byte-identical -- which is exactly why `tests/c64/test_sideprompt.py`'s
`FakeSession`, `self.here = "/slot"` compared against the literal
`"/slot/SIDE3.D64"` on both sides, cannot tell the fixed code from the bug it
is fixing.

So every test here **spies on `os.path.join` itself**: if a spot regresses to
an f-string, `os.path.join` is never called for it, and the spy's tally comes
back empty regardless of which platform the suite happens to run on.  Where a
resulting path is also asserted, it is built by calling `os.path.join` again
in the test, never a literal with a hardcoded separator.

`ntpath.join` was used once, by hand, to confirm `os.path.join` is genuinely
the fix: on a Windows-style base `C:\\Users\\someone\\work\\drive`,
`ntpath.join(base, "SIDE1.D64")` answers
`C:\\Users\\someone\\work\\drive\\SIDE1.D64`, matching a
`pathlib.PureWindowsPath`-built expectation, where the old
`f"{base}/SIDE1.D64"` answers `...drive/SIDE1.D64` and does not.  `ntpath` is
not imported into a test here because nothing in this module needs to *run*
Windows-flavoured joining -- only to prove the production code calls the one
join function that is.
"""

from __future__ import annotations

import os

from conftest import load_tools_module

from automap.screen import Screen

session = load_tools_module("session")


def screen_of(row24: str) -> Screen:
    """A `Screen` carrying *row24* on the bottom row, blank everywhere else."""
    codes = bytearray(0x20 for _ in range(1000))
    for i, ch in enumerate(row24.upper()):
        codes[24 * 40 + i] = ord(ch) - 0x40 if "A" <= ch <= "Z" else ord(ch)
    return Screen(bytes(codes), bytes(1000), 0xCC00)


class FakeSlot:
    """The handful of attributes `Session.__init__` and `.launch()` read off
    a real `tools.registry.instance.Slot`, minus the lease and the flock."""

    def __init__(self, here):
        self.dir = here
        self.port = 16502
        self.text_port = 16510
        self.cmd_port = 16600
        self.records: list[dict] = []

    def monflags(self):
        return ""

    @property
    def display(self):
        return ":9"

    def env(self):
        return {}

    def record(self, **fields):
        self.records.append(fields)


#: `os.path.join` before any test replaces it.  `session.os` is the same
#: module object as this file's own `os` -- `import os` names one process-wide
#: module -- so patching `session.os.path.join` for a spy replaces this file's
#: `os.path.join` too, and a spy that called `os.path.join` to do the real
#: work would be calling itself.
_REAL_JOIN = os.path.join


class JoinSpy:
    """Records every `os.path.join` call and still performs it, so the code
    under test keeps working while the test watches how it built the path."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, *parts):
        self.calls.append(parts)
        return _REAL_JOIN(*parts)


class FakeMon:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# -- __init__: self.disk and self.save_disk ----------------------------------


def test_init_builds_disk_and_save_disk_with_os_path_join(tmp_path, monkeypatch):
    spy = JoinSpy()
    monkeypatch.setattr(session.os.path, "join", spy)

    sess = session.Session(slot=FakeSlot(tmp_path))

    assert (str(tmp_path), "SIDE1.D64") in spy.calls
    assert (str(tmp_path), "SIDE0.D64") in spy.calls
    assert sess.disk == os.path.join(str(tmp_path), "SIDE1.D64")
    assert sess.save_disk == os.path.join(str(tmp_path), "SIDE0.D64")


# -- attach(): the bare-side-number path --------------------------------------


def test_attach_builds_the_numeric_side_path_with_os_path_join(
        tmp_path, monkeypatch):
    spy = JoinSpy()
    monkeypatch.setattr(session.os.path, "join", spy)

    sess = session.Session()
    sess.here = str(tmp_path)
    sess.attached = ""
    monkeypatch.setattr(sess, "mon", lambda timeout=5.0: FakeMon())

    class FakeText:
        def sendall(self, data):
            pass

        def recv(self, n):
            raise TimeoutError

    sess.text = FakeText()

    sess.attach("3", settle=0.0)

    assert (str(tmp_path), "SIDE3.D64") in spy.calls
    assert sess.attached == os.path.join(str(tmp_path), "SIDE3.D64")


# -- handle_prompt(): the disk-prompt side path -------------------------------


def test_handle_prompt_builds_the_side_path_with_os_path_join(
        tmp_path, monkeypatch):
    spy = JoinSpy()
    monkeypatch.setattr(session.os.path, "join", spy)

    sess = session.Session()
    sess.here = str(tmp_path)
    sess.save_disk = os.path.join(sess.here, "SIDE0.D64")
    sess.attached = ""
    sess._last_prompt = 0.0
    attached = []
    monkeypatch.setattr(sess, "attach", lambda path, **kw: attached.append(path))
    monkeypatch.setattr(sess, "log", lambda *a: None)

    class FakeKbd:
        def key(self, name, hold=0.0, gap=0.0):
            pass

    sess.kbd = FakeKbd()

    s = screen_of("INSERT SIDE # 3, AND PRESS ANY KEY.")

    assert sess.handle_prompt(s) is True
    assert (str(tmp_path), "SIDE3.D64") in spy.calls
    assert attached == [os.path.join(str(tmp_path), "SIDE3.D64")]


# -- launch(): the porlaunch.sh and vice.log paths ----------------------------


def test_launch_builds_the_porlaunch_and_log_paths_with_os_path_join(
        tmp_path, monkeypatch):
    spy = JoinSpy()
    monkeypatch.setattr(session.os.path, "join", spy)

    sess = session.Session()
    sess.here = str(tmp_path)

    popen_calls = []

    class FakeProc:
        pid = 999999

    def fake_popen(args, **kw):
        popen_calls.append((args, kw))
        return FakeProc()

    monkeypatch.setattr(session.subprocess, "Popen", fake_popen)
    # `os.getpgid` is POSIX-only and does not exist as an attribute on
    # Windows, where `monkeypatch.setattr` would otherwise fail before
    # `launch()` ever runs.  `raising=False` creates it for the duration of
    # the test on a platform that lacks it, and overrides the real one where
    # it exists -- the same behaviour either way, so `launch()`'s own
    # unconditional call to it succeeds on both.
    monkeypatch.setattr(session.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(sess, "mon", lambda timeout=3.0: FakeMon())

    class FakeSocket:
        def settimeout(self, t):
            pass

    monkeypatch.setattr(
        session.socket, "create_connection", lambda addr, timeout=5: FakeSocket())
    monkeypatch.setattr(sess, "log", lambda *a: None)
    monkeypatch.setattr(session.time, "sleep", lambda s: None)

    sess.launch()

    assert (session.TOOLS, "c64", "porlaunch.sh") in spy.calls
    assert (str(tmp_path), "vice.log") in spy.calls
    args, kw = popen_calls[0]
    assert args[0] == os.path.join(session.TOOLS, "c64", "porlaunch.sh")
