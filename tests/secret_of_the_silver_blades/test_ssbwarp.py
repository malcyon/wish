"""`tools/secret_of_the_silver_blades/ssbwarp.py`'s stuck-screen Escape must not abort a load in
progress (#568, the Silver Blades half of #334).

Escape is VICE's RUN/STOP key, which aborts a KERNAL `LOAD` still running.
`enter_world` used to send it after any `STUCK` (15s) seconds of an
unchanged screen, and a Silver Blades `ECL` script is 26-31 disk blocks --
long enough to sit with the screen unchanged the whole time while it is
still loading. The fix gates that Escape on `idle_in_key_window`, which
confirms the PC is genuinely sitting in `DUNGEON`'s key-wait loop or
`LIBRARY`'s fetcher, not merely that the screen has not changed.

Two tests. `test_idle_in_key_window_...` mocks the monitor's register read
directly, proving the gate function's own PC-window logic. The other two
drive `enter_world` itself with a fake clock and a monkeypatched gate,
proving the wiring: the Escape branch calls the gate and only presses the
key when it says the machine is idle.
"""

from __future__ import annotations

from contextlib import contextmanager

from conftest import load_tools_module

SSB = load_tools_module("ssbwarp")


class FakeRegs:
    """What `m.registers()` returns: a dict keyed by whatever id
    `pc_register` resolves to."""

    def __init__(self, pc):
        self.pc = pc

    def get(self, rid):
        return self.pc


class FakeMon:
    """A monitor stand-in with the one register id already cached, so
    `pc_register` never tries a real `mon.command()` round trip."""

    def __init__(self, pc):
        self._pc_register = 0x90
        self._pc = pc

    def registers(self):
        return FakeRegs(self._pc)


class FakeScreen:
    """`text()` is the whole screen; `row(24)` is what `enter_world` reads
    to name the state a stuck screen is in."""

    def __init__(self, text, bar=None):
        self._text = text
        self._bar = bar if bar is not None else text

    def text(self):
        return self._text

    def row(self, n):
        return self._bar


class FakeSess:
    """Just enough of `Session` for `idle_in_key_window`: a monitor context
    manager and a screen that does not change between samples."""

    def __init__(self, pc, text="A MENU"):
        self.pc = pc
        self._text = text
        self.mon_calls = 0

    @contextmanager
    def mon(self, timeout):
        self.mon_calls += 1
        yield FakeMon(self.pc)

    def screen(self):
        return FakeScreen(self._text)


class Addr:
    """The two windows `idle_in_key_window` reads, nothing else."""
    key_wait = (0x1000, 0x1010)
    key_fetch = (0x2000, 0x2010)


def test_idle_in_key_window_confirms_a_pc_genuinely_in_the_window():
    sess = FakeSess(pc=0x1005)
    pc = SSB.idle_in_key_window(sess, Addr(), samples=2, gap=0.0)
    assert pc == 0x1005


def test_idle_in_key_window_refuses_a_pc_outside_both_windows():
    """This is the load-in-progress case: the screen is not drawing
    anything new, but the PC is off running the KERNAL loader rather than
    waiting in DUNGEON's loop or LIBRARY's fetcher."""
    sess = FakeSess(pc=0xE000)
    pc = SSB.idle_in_key_window(sess, Addr(), samples=2, gap=0.0)
    assert pc is None


class FakeClock:
    """Advances only when `enter_world` sleeps, so a 15-second `STUCK`
    threshold is crossed without the test taking 15 seconds."""

    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class StuckSess:
    """A screen that never changes and never answers a prompt -- the
    `enter_world` state that used to fall straight through to Escape."""

    def __init__(self):
        self.logged: list[str] = []
        self.kbd_sent: list[str] = []

        outer = self

        class Kbd:
            def key(self, name):
                outer.kbd_sent.append(name)

        self.kbd = Kbd()

    def screen(self):
        return FakeScreen("SOME MENU", bar="SOME MENU")

    def handle_prompt(self, s=None):
        return False

    def log(self, *a):
        self.logged.append(" ".join(str(x) for x in a))


def _make_stuck_sess():
    sess = StuckSess()
    return sess, sess.kbd_sent


def test_enter_world_does_not_escape_a_screen_stuck_by_a_slow_load(
        monkeypatch):
    """Red without the fix: `idle_in_key_window` returning None (the PC is
    off in the KERNAL loader, not a key window) must not stop `enter_world`
    from pressing Escape into it."""
    clock = FakeClock()
    monkeypatch.setattr(SSB.time, "time", clock.time)
    monkeypatch.setattr(SSB.time, "sleep", clock.sleep)
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: None)
    sess, sent = _make_stuck_sess()
    ok = SSB.enter_world(sess, Addr(), timeout=40.0, fix=False,
                         stop_at_idle=False)
    assert ok is False
    assert "Escape" not in sent


def test_enter_world_escapes_once_the_pc_is_genuinely_idle(monkeypatch):
    """The other half: with the gate reporting the machine is really sitting
    in a key window, the stuck screen is answered with Escape as before."""
    clock = FakeClock()
    monkeypatch.setattr(SSB.time, "time", clock.time)
    monkeypatch.setattr(SSB.time, "sleep", clock.sleep)
    monkeypatch.setattr(SSB, "idle_in_key_window",
                        lambda sess, addr: 0x1005)
    sess, sent = _make_stuck_sess()
    ok = SSB.enter_world(sess, Addr(), timeout=40.0, fix=False,
                         stop_at_idle=False)
    assert ok is False
    assert "Escape" in sent
