"""`tools/secret_of_the_silver_blades/ssbsession.py`'s stuck-screen Escape must not abort a load in
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

import os
from contextlib import contextmanager

from conftest import load_tools_module
from support.partymenu import BEGIN_ROW, ENTRIES, menu_screen

SSB = load_tools_module("ssbsession")


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

    def iec_stall_check(self):
        return False

    def stall_capture(self):
        return "captured"

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


def test_a_prompt_still_up_after_the_key_is_not_answered_again(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(SSB.time, "time", lambda: now[0])
    keys = []

    class Session(SSB.SSBSession):
        def __init__(self):
            self.here = "/slot"
            self.attached = "/slot/SIDE1.D64"
            self.save_disk = "/slot/SIDE0.D64"
            self._last_prompt = 0.0
            self.kbd = type("Kbd", (), {"key": lambda k, name: keys.append(name)})()

        def attach(self, path, *a, **k):
            now[0] += 3.5
            self.attached = os.path.abspath(path)

        def log(self, *a):
            pass

    sess = Session()
    monkeypatch.setattr(SSB.os.path, "exists", lambda p: True)
    screen = FakeScreen("INSERT SIDE # 2, AND PRESS ANY KEY.")
    assert sess.handle_prompt(screen)
    # Each probe is inside the hold and past the two-second cooldown after
    # the first, so the hold's length and the restamp after the key are pinned.
    for step in (0.35, 2.15, 2.5, 2.5):
        now[0] += step
        assert not sess.handle_prompt(screen)
    now[0] += 1.0
    assert sess.handle_prompt(screen)
    assert keys == ["space", "space"]


class WorldSess:
    """Plays a fixed list of (text, row 24) screens, one per `screen()` call,
    repeating the last, and records every key `enter_world` sends."""

    def __init__(self, screens, prompt_at=()):
        self.screens = list(screens)
        self.prompt_at = set(prompt_at)
        self.calls = 0
        self.selected: list[str] = []
        self.kernal: list[int] = []
        self.escapes = 0
        self.kernal_after_world_bar = 0
        self.world_bar_seen = False
        outer = self

        class Kbd:
            def key(self, name):
                if name == "Escape":
                    outer.escapes += 1

        self.kbd = Kbd()

    def screen(self):
        i = min(self.calls, len(self.screens) - 1)
        self.calls += 1
        self.current = i
        text, bar = self.screens[i]
        if "ENCAMP" in text:
            self.world_bar_seen = True
        if text == "BEGIN ADVENTURING":
            # The menu waiting for a key, or the same menu once the load has
            # started: real screens, so `load_started` reads real colour.
            return menu_screen(3 if bar == text else None,
                               row24="" if bar == text else bar)
        return FakeScreen(text, bar=bar)

    def handle_prompt(self, s=None):
        return self.current in self.prompt_at

    def iec_stall_check(self):
        self.stall_checks = getattr(self, "stall_checks", 0) + 1
        return self.stall_checks > getattr(self, "stall_after", 10**9)

    def stall_capture(self):
        return "captured"

    def select_row(self, label):
        self.selected.append(label)

    def press_kernal(self, code):
        self.kernal.append(code)
        if self.world_bar_seen:
            self.kernal_after_world_bar += 1

    def log(self, *a):
        pass


def _quiet(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(SSB.time, "time", clock.time)
    monkeypatch.setattr(SSB.time, "sleep", clock.sleep)
    monkeypatch.setattr(SSB, "impossible_side", lambda *a, **k: None)
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: None)


MENU = ("BEGIN ADVENTURING", "BEGIN ADVENTURING")
PROMPT = ("INSERT SIDE A, AND PRESS ANY KEY.", "INSERT SIDE A, AND PRESS ANY KEY.")
WORLD = ("MOVE VIEW CAST AREA ENCAMP SEARCH LOOK",
         "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK")


def test_a_menu_left_drawn_while_the_area_loads_is_not_chosen_again(
        monkeypatch):
    _quiet(monkeypatch)
    sess = WorldSess([MENU, PROMPT] + [MENU] * 5 + [WORLD], prompt_at={1})
    ok = SSB.enter_world(sess, Addr(), timeout=120.0, fix=False,
                         stop_at_idle=False)
    assert ok is True
    assert sess.selected == ["BEGIN ADVENTURING"]
    assert sess.kernal_after_world_bar == 0


def test_the_move_subbar_after_begin_gets_one_return_and_no_escape(
        monkeypatch):
    _quiet(monkeypatch)
    subbar = ("MOVE", "I,J,K,M, RETURN OR BUTTON")

    class Sess(WorldSess):
        def press_kernal(self, code):
            super().press_kernal(code)
            if self.screens[self.current] is subbar:
                self.screens.append(WORLD)

    sess = Sess([MENU, PROMPT, subbar], prompt_at={1})
    sess.screens = [MENU, PROMPT, subbar]
    ok = SSB.enter_world(sess, Addr(), timeout=120.0, fix=False,
                         stop_at_idle=False)
    assert ok is True
    # One Return chose BEGIN; exactly one more left the sub-bar.
    assert sess.kernal == [0x0D, 0x0D]
    assert sess.escapes == 0


def test_the_move_subbar_that_persists_gets_at_most_two_returns(monkeypatch):
    _quiet(monkeypatch)
    subbar = ("MOVE", "I,J,K,M, RETURN OR BUTTON")
    sess = WorldSess([MENU, PROMPT, subbar], prompt_at={1})
    ok = SSB.enter_world(sess, Addr(), timeout=60.0, fix=False,
                         stop_at_idle=False)
    assert ok is False
    # One Return chose BEGIN; the sub-bar then got two, not one per pass.
    assert sess.kernal == [0x0D] * 3
    assert sess.escapes == 0


def test_the_move_subbar_is_left_before_the_idle_exit(monkeypatch):
    _quiet(monkeypatch)
    # An idle PC would end the run from the fetcher if the sub-bar branch did
    # not come first.
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: 0x1005)
    subbar = ("MOVE", "I,J,K,M, RETURN OR BUTTON")
    other = ("A SCREEN", "A SCREEN")

    class Sess(WorldSess):
        def press_kernal(self, code):
            super().press_kernal(code)
            if self.screens[self.current] is subbar:
                self.screens.append(WORLD)

    sess = Sess([MENU, PROMPT, other, subbar], prompt_at={1})
    ok = SSB.enter_world(sess, Addr(), timeout=120.0, fix=False,
                         stop_at_idle=True)
    assert ok is True
    assert sess.kernal == [0x0D, 0x0D]


def test_a_menu_still_up_after_90_seconds_with_no_prompt_is_chosen_again(
        monkeypatch):
    _quiet(monkeypatch)
    sess = WorldSess([MENU], prompt_at=())
    SSB.enter_world(sess, Addr(), timeout=150.0, fix=False,
                    stop_at_idle=False)
    assert sess.selected == ["BEGIN ADVENTURING"] * 2


def test_a_menu_still_up_after_90_seconds_is_not_chosen_again_once_a_prompt_was_answered(
        monkeypatch):
    _quiet(monkeypatch)
    sess = WorldSess([MENU, PROMPT, MENU], prompt_at={1})
    SSB.enter_world(sess, Addr(), timeout=150.0, fix=False,
                    stop_at_idle=False)
    assert sess.selected == ["BEGIN ADVENTURING"]


def test_a_load_that_stalls_gives_up_at_once_instead_of_running_out_the_clock(
        monkeypatch):
    _quiet(monkeypatch)
    sess = WorldSess([MENU, PROMPT, MENU], prompt_at={1})
    sess.stall_after = 3
    ok = SSB.enter_world(sess, Addr(), timeout=600.0, fix=False,
                         stop_at_idle=False)
    assert ok is False
    assert sess.stall_checks == 4
    assert sess.kernal == [0x0D]


def test_a_started_load_gets_no_further_walk_or_return_after_90_seconds(
        monkeypatch):
    _quiet(monkeypatch)
    started = ("BEGIN ADVENTURING", "ONWARD BOUND")
    sess = WorldSess([MENU, started], prompt_at=())
    ok = SSB.enter_world(sess, Addr(), timeout=150.0, fix=False,
                         stop_at_idle=False)
    assert ok is False
    assert sess.selected == ["BEGIN ADVENTURING"]
    assert sess.kernal == [0x0D]


def test_load_started_reads_a_real_screen_both_ways():
    waiting = menu_screen(cursor=3)
    assert waiting.find("BEGIN ADVENTURING") == (BEGIN_ROW, 2)
    assert waiting.row(24).strip() == ""
    assert SSB.load_started(waiting) is False
    started = menu_screen(cursor=None, row24="ONWARD BOUND")
    assert SSB.load_started(started) is True
    # Row 24 alone is not enough: an entry still white is a menu waiting.
    assert SSB.load_started(menu_screen(3, row24="ONWARD BOUND")) is False
    assert SSB.load_started(menu_screen(len(ENTRIES) - 1)) is False
    assert SSB.load_started(menu_screen(None)) is False
