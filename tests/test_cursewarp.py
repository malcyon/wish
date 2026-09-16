"""`tools/cursewarp.py`'s stuck-screen Escape has the identical vulnerability
`tests/test_ssbwarp.py` covers for Silver Blades (#568, general defect;
`#334`'s own Silver Blades half is where it was first traced).

Escape is VICE's RUN/STOP key, which aborts a KERNAL `LOAD` still running.
`enter_world` used to send it after any `STUCK` (15s) seconds of an
unchanged screen -- exempting only a literally blank one, not a screen
showing old content while a slow ECL load runs underneath it. The fix gates
that Escape on `idle_in_key_window`, a single PC read against the same
`key_wait`/`key_fetch` windows `wait_idle` already polls after a warp.

**`addr` is optional on `enter_world` here**, because `tools/livecheck.py`,
`tools/inventorycheck.py` and `tools/cursecheck.py` -- none of them this
file's own -- call it without one; those calls keep the old unconditional
Escape.
"""

from __future__ import annotations

from contextlib import contextmanager

from conftest import load_tools_module

CURSE = load_tools_module("cursewarp")


class FakeRegs:
    def __init__(self, pc):
        self.pc = pc

    def get(self, rid):
        return self.pc


class FakeMon:
    def __init__(self, pc):
        self._pc_register = 0x90
        self._pc = pc

    def registers(self):
        return FakeRegs(self._pc)


class FakeSess:
    """Just enough of `Session` for `idle_in_key_window`: a monitor context
    manager."""

    def __init__(self, pc):
        self.pc = pc

    @contextmanager
    def mon(self, timeout):
        yield FakeMon(self.pc)


class Addr:
    key_wait = (0x1000, 0x1010)
    key_fetch = (0x2000, 0x2010)


def test_idle_in_key_window_confirms_a_pc_genuinely_in_the_window():
    sess = FakeSess(pc=0x2005)
    assert CURSE.idle_in_key_window(sess, Addr()) == 0x2005


def test_idle_in_key_window_refuses_a_pc_outside_both_windows():
    """The load-in-progress case: the screen has not changed, but the PC is
    off in the KERNAL loader rather than waiting in a key window."""
    sess = FakeSess(pc=0xE000)
    assert CURSE.idle_in_key_window(sess, Addr()) is None


class FakeScreen:
    def __init__(self, text, bar=None):
        self._text = text
        self._bar = bar if bar is not None else text

    def text(self):
        return self._text

    def row(self, n):
        return self._bar


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class StuckSess:
    """A screen that never changes and never answers a prompt -- the state
    `enter_world` used to escape out of unconditionally."""

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
    """Red without the fix: `idle_in_key_window` returning None must not
    stop `enter_world` from pressing Escape into a load still running."""
    clock = FakeClock()
    monkeypatch.setattr(CURSE.time, "time", clock.time)
    monkeypatch.setattr(CURSE.time, "sleep", clock.sleep)
    monkeypatch.setattr(CURSE, "idle_in_key_window",
                        lambda sess, addr: None)
    sess, sent = _make_stuck_sess()
    ok = CURSE.enter_world(sess, Addr(), timeout=40.0)
    assert ok is False
    assert "Escape" not in sent


def test_enter_world_escapes_once_the_pc_is_genuinely_idle(monkeypatch):
    """The other half: a machine really sitting in a key window still gets
    Escape as before."""
    clock = FakeClock()
    monkeypatch.setattr(CURSE.time, "time", clock.time)
    monkeypatch.setattr(CURSE.time, "sleep", clock.sleep)
    monkeypatch.setattr(CURSE, "idle_in_key_window",
                        lambda sess, addr: 0x1005)
    sess, sent = _make_stuck_sess()
    ok = CURSE.enter_world(sess, Addr(), timeout=40.0)
    assert ok is False
    assert "Escape" in sent


def test_enter_world_without_addr_keeps_the_old_unconditional_escape(
        monkeypatch):
    """The three callers that do not pass `addr` -- `tools/livecheck.py`,
    `tools/inventorycheck.py`, `tools/cursecheck.py` -- must see the same
    behaviour as before this fix, since none of them is this ticket's file
    to change."""
    clock = FakeClock()
    monkeypatch.setattr(CURSE.time, "time", clock.time)
    monkeypatch.setattr(CURSE.time, "sleep", clock.sleep)
    sess, sent = _make_stuck_sess()
    ok = CURSE.enter_world(sess, timeout=40.0)
    assert ok is False
    assert "Escape" in sent
