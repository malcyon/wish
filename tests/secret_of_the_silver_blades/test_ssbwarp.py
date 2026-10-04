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
from support.partymenu import (
    BEGIN_ROW,
    ENTRIES,
    MODIFY,
    PARTY,
    SIDE_2,
    menu_screen,
    picker_screen,
)

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
    mode = 0x7F11


def test_idle_in_key_window_confirms_a_pc_genuinely_in_the_window():
    sess = FakeSess(pc=0x1005)
    pc = SSB.idle_in_key_window(sess, Addr(), samples=2, gap=0.0)
    assert pc == 0x1005


def test_idle_in_key_window_rejects_a_pc_outside_both_windows():
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

    def __init__(self, screens, prompt_at=(), walk_ok=True):
        self.screens = list(screens)
        self.prompt_at = set(prompt_at)
        self.walk_ok = walk_ok
        self.walked: str | None = None
        self.after_walk = None
        self.bars: list[str] = []
        self.calls = 0
        self.selected: list[str] = []
        self.kernal: list[int] = []
        #: The screen up at each keyboard-buffer Return, and every line logged.
        self.returned_at: list = []
        self.logged: list[str] = []
        self.shown = None
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
        self.shown = self._screen()
        return self.shown

    def _screen(self):
        if self.walked is not None:
            # The read straight after a walk that reached its row: the same
            # screen with the highlight moved there, the script not advanced
            # -- or whatever `after_walk` says the game had put up by then.
            label, self.walked = self.walked, None
            if self.after_walk is not None:
                return self.after_walk
            if label == "EXIT":
                return picker_screen(len(PARTY))
            return menu_screen(ENTRIES.index(label))
        i = min(self.calls, len(self.screens) - 1)
        self.calls += 1
        self.current = i
        item = self.screens[i]
        if not isinstance(item, tuple):
            return item                 # a real `Screen`
        text, bar = item
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

    def select_row(self, label, **walk):
        self.selected.append(label)
        if self.walk_ok:
            self.walked = label
        return self.walk_ok

    def select_bar(self, label, **kw):
        self.bars.append(label)
        return True

    def press_kernal(self, code):
        self.kernal.append(code)
        self.returned_at.append(self.shown)
        if self.world_bar_seen:
            self.kernal_after_world_bar += 1

    def log(self, *a):
        self.logged.append(" ".join(str(x) for x in a))


class Modes:
    """LINKER's mode byte, one value per read, the last one repeating; None
    is a failed read. Records how many reads were made."""

    def __init__(self, values):
        self.values = list(values) if isinstance(values, (list, tuple)) \
            else [values]
        self.reads = 0
        self.last = "unread"

    def __call__(self, sess, addr, errors=None):
        v = self.values[min(self.reads, len(self.values) - 1)]
        self.reads += 1
        self.last = v
        if v is None and errors is not None:
            errors.append(OSError("monitor did not answer"))
        return v


def _quiet(monkeypatch, mode=1):
    clock = FakeClock()
    monkeypatch.setattr(SSB.time, "time", clock.time)
    monkeypatch.setattr(SSB.time, "sleep", clock.sleep)
    monkeypatch.setattr(SSB, "impossible_side", lambda *a, **k: None)
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: None)
    # LINKER's mode byte: 1 is DUNGEON, the world; 0 is GEN, the party menu.
    modes = Modes(mode)
    monkeypatch.setattr(SSB, "overlay_mode", modes, raising=False)
    return modes


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


def _verified(screen) -> bool:
    """A keyboard-buffer Return went to a screen whose highlight was checked:
    BEGIN ADVENTURING on the menu, or EXIT on a party list."""
    return (screen is not None and hasattr(screen, "colours")
            and (menu_cursor_is_begin(screen) or picker_exit_hot(screen)))


def menu_cursor_is_begin(screen) -> bool:
    hit = screen.find("BEGIN ADVENTURING")
    return hit is not None and screen.colours[hit[0] * 40 + hit[1]] == 1 \
        and all(screen.colours[(hit[0] - i) * 40 + hit[1]] != 1
                for i in range(1, len(ENTRIES)))


def picker_exit_hot(screen) -> bool:
    hit = screen.find("EXIT")
    return (hit is not None and "WHICH CHARACTER" in screen.row(24)
            and screen.colours[hit[0] * 40 + hit[1]] == 1)


def test_a_walk_that_fails_sends_no_return_and_gives_up_saying_why(
        monkeypatch):
    """#796: the highlight sits on MODIFY CHARACTER and every walk fails --
    a dialog took the arrow keys. A Return then would choose MODIFY."""
    _quiet(monkeypatch)
    sess = WorldSess([menu_screen(MODIFY)], walk_ok=False)
    ok = SSB.enter_world(sess, Addr(), timeout=600.0, fix=False,
                         stop_at_idle=True)
    assert ok is False
    assert sess.kernal == []
    assert sess.selected == ["BEGIN ADVENTURING"] * SSB.MAX_WALKS
    assert any("giving up" in line for line in sess.logged)


def test_modify_which_character_is_not_the_world_and_is_left_through_exit(
        monkeypatch):
    """#796: the stray Return opened `MODIFY WHICH CHARACTER?`, GEN is still
    the running overlay and the PC waits in the shared fetcher. The list is
    left through EXIT, BEGIN ADVENTURING is chosen again, and True comes only
    from the world bar."""
    _quiet(monkeypatch, mode=0)
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: 0x410B)
    sess = WorldSess([menu_screen(MODIFY), picker_screen(0),
                      menu_screen(MODIFY), WORLD])
    ok = SSB.enter_world(sess, Addr(), timeout=240.0, fix=False,
                         stop_at_idle=True)
    assert ok is True
    assert sess.world_bar_seen
    assert sess.selected == ["BEGIN ADVENTURING", "EXIT", "BEGIN ADVENTURING"]
    assert sess.kernal == [0x0D] * 3
    assert all(_verified(s) for s in sess.returned_at)


def test_a_party_list_that_will_not_close_is_never_the_world(monkeypatch):
    _quiet(monkeypatch, mode=0)
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: 0x410B)
    sess = WorldSess([menu_screen(MODIFY), picker_screen(0)])
    ok = SSB.enter_world(sess, Addr(), timeout=240.0, fix=False,
                         stop_at_idle=True)
    assert ok is False
    assert sess.selected.count("EXIT") == SSB.MAX_BACKOUTS
    assert all(_verified(s) for s in sess.returned_at)


def test_a_screen_past_the_menu_with_gen_still_running_is_not_the_world(
        monkeypatch):
    """No list, no bar this loop knows, and the PC idle in the fetcher: with
    LINKER's byte at 0 it is still the front end, so no True and no Escape."""
    _quiet(monkeypatch, mode=0)
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: 0x410B)
    escapes = []
    sess = WorldSess([MENU, ("A SCREEN", "A SCREEN")])
    sess.kbd = type("Kbd", (), {"key": lambda k, name: escapes.append(name)})()
    ok = SSB.enter_world(sess, Addr(), timeout=240.0, fix=False,
                         stop_at_idle=True)
    assert ok is False
    assert escapes == []
    assert any("no known way out" in line for line in sess.logged)


def test_the_highlight_readers_on_real_screens():
    assert SSB.cursor_on_begin(menu_screen(len(ENTRIES) - 1))
    assert not SSB.cursor_on_begin(menu_screen(MODIFY))
    assert not SSB.cursor_on_begin(menu_screen(None))
    assert SSB.at_picker(picker_screen(0))
    assert not SSB.at_picker(menu_screen(MODIFY))
    assert SSB.picker_on_exit(picker_screen(len(PARTY)))
    assert not SSB.picker_on_exit(picker_screen(0))


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
    # Nor is row 24 needed: a disk prompt replaces `ONWARD BOUND` during the
    # load, and once it is answered row 24 is blank under the same menu.
    assert SSB.load_started(menu_screen(None, row24=SIDE_2)) is True
    assert SSB.load_started(menu_screen(None)) is True



def test_a_post_walk_screen_with_a_disk_prompt_gets_no_return(monkeypatch):
    """The walk reached BEGIN and the game took its Return at once: the side
    prompt is drawn when the screen is read again, and a Return there would
    answer it with the wrong side in the drive."""
    _quiet(monkeypatch)
    sess = WorldSess([MENU, PROMPT, WORLD], prompt_at={1})
    sess.after_walk = menu_screen(len(ENTRIES) - 1, row24=SIDE_2)
    assert SSB.enter_world(sess, Addr(), timeout=120.0, fix=False,
                           stop_at_idle=False) is True
    assert sess.selected == ["BEGIN ADVENTURING"]
    assert sess.kernal == []


def test_a_post_walk_screen_with_no_entry_white_gets_no_return(monkeypatch):
    """The game took the walk's own Return and cleared the highlight: the
    load has started, and a second Return would go into it."""
    _quiet(monkeypatch)
    sess = WorldSess([MENU, WORLD])
    sess.after_walk = menu_screen(None, row24="ONWARD BOUND")
    assert SSB.enter_world(sess, Addr(), timeout=120.0, fix=False,
                           stop_at_idle=False) is True
    assert sess.kernal == []


TREASURE = ("VIEW TAKE POOL SHARE EXIT", "VIEW TAKE POOL SHARE EXIT")


def test_nothing_is_pressed_after_begin_until_the_mode_leaves_gen(
        monkeypatch):
    """A bar with EXIT on it while the mode byte still reads 0 gets nothing;
    the same bar once DUNGEON runs gets its EXIT. The opening scene is due,
    the one place a treasure bar is left behind (#801)."""
    modes = _quiet(monkeypatch, mode=[0] * 6 + [1])
    monkeypatch.setattr(SSB, "opening_scene_due", lambda sess: True)
    pressed_at: list = []

    class Sess(WorldSess):
        def select_bar(self, label, **kw):
            pressed_at.append(modes.last)
            return super().select_bar(label, **kw)

    sess = Sess([MENU] + [TREASURE] * 12 + [WORLD])
    assert SSB.enter_world(sess, Addr(), timeout=240.0, fix=False,
                           stop_at_idle=False) is True
    # One read per pass: six passes at mode 0 with nothing pressed, then the
    # read of 1, after which nothing more needs reading.
    assert modes.reads == 7
    assert pressed_at and set(pressed_at) == {1}
    # EXIT is chosen by `select_bar`'s own Return; a KERNAL Return after it
    # would reach the next bar's highlighted word (#801).
    assert sess.bars and set(sess.bars) == {"EXIT"}
    assert sess.kernal == [0x0D]


def test_a_slow_load_out_of_gen_is_waited_for_not_given_up(monkeypatch):
    """Mode 0 for a minute with the screen unchanged and the PC not in a key
    window (the load of DUNGEON still running): no give-up, no key."""
    _quiet(monkeypatch, mode=[0] * 40 + [1])
    escapes = []
    sess = WorldSess([MENU] + [("A SCREEN", "A SCREEN")] * 45 + [WORLD])
    sess.kbd = type("Kbd", (), {"key": lambda k, name: escapes.append(name)})()
    assert SSB.enter_world(sess, Addr(), timeout=600.0, fix=False,
                           stop_at_idle=False) is True
    assert escapes == [] and sess.kernal == [0x0D]
    assert not any("giving up" in line for line in sess.logged)


def test_post_com_is_the_world_but_not_a_place_to_warp_from(monkeypatch):
    """Mode 5, POST.COM's treasure after a fight: past the party menu, so the
    party is in the world, but the idle exit waits for DUNGEON."""
    _quiet(monkeypatch, mode=[5] * 4 + [1])
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: 0x410B)
    sess = WorldSess([MENU] + [("A SCREEN", "A SCREEN")] * 10)
    assert SSB.enter_world(sess, Addr(), timeout=240.0, fix=False,
                           stop_at_idle=True) is True
    assert any("mode 5" in line for line in sess.logged)
    assert any("warpable" in line for line in sess.logged)
    assert SSB.overlay_mode.reads == 5


def test_a_mode_byte_that_cannot_be_read_stops_the_load_saying_why(
        monkeypatch):
    modes = _quiet(monkeypatch, mode=None)
    sess = WorldSess([MENU] + [("A SCREEN", "A SCREEN")])
    assert SSB.enter_world(sess, Addr(), timeout=600.0, fix=False,
                           stop_at_idle=True) is False
    assert modes.reads == SSB.MAX_MODE_FAILURES
    assert sess.kernal == [0x0D]
    first = [line for line in sess.logged if "could not read" in line]
    assert len(first) == 1 and "monitor did not answer" in first[0]
    assert "times running" in sess.logged[-1]


class StallSess(WorldSess):
    """A drive stall under an unchanged screen: `iec_stall_check` sees it
    once the screen has sat for more than 15 s. With `recover` it nudges the
    drive and the load goes on; without, it gives up, as the real check
    does after its nudges fail."""

    def __init__(self, screens, clock, recover):
        super().__init__(screens)
        self.clock, self.recover = clock, recover
        self.still_since: float | None = None
        self.nudges = 0
        self.stalled = False

    def iec_stall_check(self):
        if (self.still_since is not None and not self.nudges
                and self.clock.t - self.still_since > 15.0):
            self.nudges += 1
            if not self.recover:
                return True
            self.screens.append(WORLD)
            self.calls = len(self.screens) - 1
        return False

    def _screen(self):
        got = super()._screen()
        if getattr(got, "_text", None) == "A SCREEN" \
                and self.still_since is None:
            self.still_since = self.clock.t
        return got


def _stall_case(monkeypatch, recover):
    modes = _quiet(monkeypatch, mode=0)
    clock = FakeClock()
    monkeypatch.setattr(SSB.time, "time", clock.time)
    monkeypatch.setattr(SSB.time, "sleep", clock.sleep)
    # The worst case for the order of the checks: an idle PC on offer too.
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: 0x410B)
    sess = StallSess([MENU] + [("A SCREEN", "A SCREEN")] * 40, clock,
                     recover)
    if recover:
        modes.values = [0] * 12 + [1]
    return sess


def test_a_drive_stall_under_gen_is_nudged_before_any_give_up(monkeypatch):
    sess = _stall_case(monkeypatch, recover=True)
    assert SSB.enter_world(sess, Addr(), timeout=240.0, fix=False,
                           stop_at_idle=False) is True
    assert sess.nudges == 1
    assert not any("no known way out" in line for line in sess.logged)


def test_a_drive_stall_that_gives_up_is_the_reason_given(monkeypatch):
    sess = _stall_case(monkeypatch, recover=False)
    assert SSB.enter_world(sess, Addr(), timeout=240.0, fix=False,
                           stop_at_idle=False) is False
    assert sess.nudges == 1
    assert not any("no known way out" in line for line in sess.logged)


def test_an_idle_pc_under_a_disk_prompt_with_gen_running_is_no_give_up(
        monkeypatch):
    """A side prompt `handle_prompt` holds back from answering again sits
    unchanged, GEN's mode byte and a PC in LIBRARY: waited out, not ended."""
    _quiet(monkeypatch, mode=[0] * 25 + [1])
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: 0x410B)
    sess = WorldSess([MENU] + [PROMPT] * 30 + [WORLD])
    assert SSB.enter_world(sess, Addr(), timeout=240.0, fix=False,
                           stop_at_idle=False) is True
    assert not any("giving up" in line for line in sess.logged)
    assert sess.kernal == [0x0D]
