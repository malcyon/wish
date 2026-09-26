from __future__ import annotations

import contextlib
import os
import pathlib
from types import SimpleNamespace

import pytest
from conftest import load_tools_module

C = load_tools_module("curserun")

SLOT = pathlib.Path("/slot").resolve()


class FakeMonitor:
    def __init__(self, side: int, reads: list[tuple[int, int]]):
        self.side = side
        self.reads = reads

    def read(self, address: int, size: int) -> bytes:
        self.reads.append((address, size))
        return bytes([self.side])


class FakeSession(C.CurseSession):
    def __init__(self, side: int, attached: str = str(SLOT / "SIDE0.D64")):
        self.here = str(SLOT)
        self.attached = attached
        self.side = side
        self.reads: list[tuple[int, int]] = []
        self.events: list[tuple[str, str | int]] = []
        self._last_prompt = 0.0
        self.save_disk = str(SLOT / "SIDE0.D64")

    def mon(self, timeout: float = 5.0):
        return contextlib.nullcontext(FakeMonitor(self.side, self.reads))

    def log(self, message: str) -> None:
        self.events.append(("log", message))

    def attach(self, path: str) -> None:
        path = os.path.abspath(path)
        self.events.append(("attach", path))
        self.attached = path

    def press_kernal(self, code: int, timeout: float = 3.0) -> bool:
        self.events.append(("kernal", code))
        return True


def base_begin(session: FakeSession) -> bool:
    session.events.append(("begin", session.attached))
    return True


def test_begin_adventuring_mounts_the_saved_side_before_entering(monkeypatch):
    monkeypatch.setattr(C.por.Session, "begin_adventuring", base_begin)
    session = FakeSession(side=2)

    assert session.begin_adventuring()

    assert session.reads == [(0x4BEE, 1)]
    assert ("attach", str(SLOT / "SIDE2.D64")) in session.events
    assert session.events[-1] == ("begin", str(SLOT / "SIDE2.D64"))


@pytest.mark.parametrize("side", [0, len(C.SIDES) + 1])
def test_begin_adventuring_leaves_an_invalid_saved_side_to_the_prompt(
        monkeypatch, side):
    monkeypatch.setattr(C.por.Session, "begin_adventuring", base_begin)
    session = FakeSession(side=side)

    assert session.begin_adventuring()

    assert not [event for event in session.events if event[0] == "attach"]
    assert session.events[-1] == ("begin", str(SLOT / "SIDE0.D64"))


def test_begin_adventuring_does_not_remount_the_current_side(monkeypatch):
    monkeypatch.setattr(C.por.Session, "begin_adventuring", base_begin)
    session = FakeSession(side=2, attached=str(SLOT / "SIDE2.D64"))

    assert session.begin_adventuring()

    assert not [event for event in session.events if event[0] == "attach"]
    assert session.events[-1] == ("begin", str(SLOT / "SIDE2.D64"))


def test_disk_prompt_uses_the_key_path_the_game_reads():
    session = FakeSession(side=2)
    screen = SimpleNamespace(text=lambda: "INSERT SIDE # 2, AND PRESS ANY KEY.")

    assert session.handle_prompt(screen)

    assert ("attach", str(SLOT / "SIDE2.D64")) in session.events
    assert session.events[-1] == ("kernal", 0x20)


class FakeBootScreen:
    """A screen `CurseSession.boot` reads through `screen_text` and `.text()`."""

    def __init__(self, text: str):
        self._text = text

    def text(self) -> str:
        return self._text

    def rows(self):
        return [self._text]


class FakeBootDisplay:
    """The nested display's windows, and the keys `dismiss_error_dialog` sent."""

    def __init__(self):
        self.windows: dict[int, str] = {1: "VICE (C64SC)"}

    def xdo(self, display, *args):
        if args[0] == "search":
            return " ".join(str(w) for w in self.windows)
        if args[0] == "getwindowname":
            return self.windows[int(args[1])]
        return ""


class FakeBootGame:
    """A C64 whose fastloader-answer keypress is swallowed once.

    A VICE dialog that grabs the keyboard eats exactly the first `y`; the
    game only sees the second.  `screen()` stays on the fastloader prompt
    until a key is actually taken, then jumps straight to the party menu.
    """

    def __init__(self):
        self.deaf = 1
        self.sent: list[str] = []
        self.taken = False

    def key(self, name, *a):
        self.sent.append(name)
        if self.deaf > 0:
            self.deaf -= 1
            return
        self.taken = True

    def screen(self):
        return FakeBootScreen("CREATE NEW CHARACTER" if self.taken
                              else "DISABLE FASTLOADER (Y/N) ?")


class FakeClock:
    """A `time` stand-in whose clock only moves when `sleep` is asked to."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_boot_resends_a_fastloader_answer_a_vice_dialog_swallowed(monkeypatch):
    """`#642 (A driven C64 Curse boot waits out its timeout when a VICE
    dialog swallows the fastloader answer)`: the first `y` never reaches the
    game, and the unfixed boot sends it once and then just waits."""
    display = FakeBootDisplay()
    game = FakeBootGame()
    order: list[str] = []

    def xdo(disp, *args):
        if args[0] == "search":
            order.append("dialog-check")
        return display.xdo(disp, *args)

    def key(name, *a):
        order.append("send")
        game.key(name, *a)

    sess = C.CurseSession()
    sess.here = str(SLOT)
    sess.kbd = SimpleNamespace(key=key)
    sess.boot_failure = None
    clock = FakeClock()
    monkeypatch.setattr(C, "time", clock)
    monkeypatch.setattr(C.por, "_xdo", xdo)
    monkeypatch.setattr(C.por, "ANSWER_RESEND", 0.05)
    monkeypatch.setattr(C.por.Session, "DIALOG_SETTLE", 0.0)
    monkeypatch.setattr(sess, "launch", lambda: None)
    monkeypatch.setattr(sess, "log", lambda *a: None)
    monkeypatch.setattr(sess, "screen", game.screen)
    monkeypatch.setattr(sess, "wait_text",
                        lambda needle, timeout=180.0: (needle, game.screen()))

    assert sess.boot() is True

    assert game.sent == ["y", "y"]
    assert order == ["dialog-check", "send", "dialog-check", "send"]


def test_a_prompt_still_up_after_the_key_is_not_answered_again(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(C.time, "time", lambda: now[0])
    session = FakeSession(side=2)
    session.attach = lambda path: now.__setitem__(0, now[0] + 3.5)
    screen = SimpleNamespace(text=lambda: "INSERT SIDE # 2, AND PRESS ANY KEY.")

    assert session.handle_prompt(screen)
    # 2.5 s is past the cooldown, 5 s pins the restamp after the key, 7.5 s
    # pins the hold's length from inside and 8.5 s from outside.
    for step in (0.35, 2.15, 2.5, 2.5):
        now[0] += step
        assert not session.handle_prompt(screen)
    now[0] += 1.0
    assert session.handle_prompt(screen)
    assert [e for e in session.events if e[0] == "kernal"] == [("kernal", 0x20)] * 2


def test_walk_one_that_may_not_answer_leaves_a_disk_prompt_alone():
    session = FakeSession(side=2)
    session.screen = lambda: SimpleNamespace(
        text=lambda: "INSERT SIDE # 2, AND PRESS ANY KEY.",
        row=lambda r: "INSERT SIDE # 2, AND PRESS ANY KEY.")
    assert session.walk_one("I", answer_prompts=False) is False
    assert session.walk_prompt == "INSERT SIDE # 2, AND PRESS ANY KEY."
    assert session.walk_refused is None
    assert session.events == []


SIDE_PROMPT = "INSERT SIDE # 2, AND PRESS ANY KEY."
MOVE_BAR = C.por.MOVE_SUBBAR


def _screen(row24: str):
    return SimpleNamespace(text=lambda: row24, row=lambda r: row24,
                           contains=lambda needle: needle in row24)


class BarSession(FakeSession):
    """`select_bar` honours its contract: a disk prompt that opens inside it
    is answered unless the caller passed `answer_prompts=False`."""

    def __init__(self, rows, side=2):
        super().__init__(side)
        self.rows = list(rows)
        self.bar_calls: list[tuple] = []
        self.opens_prompt = True

    def screen(self):
        return _screen(self.rows.pop(0) if len(self.rows) > 1 else self.rows[0])

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.bar_calls.append((label, answer_prompts))
        if self.opens_prompt:
            self.rows = [SIDE_PROMPT]
            if answer_prompts:
                self.handle_prompt(_screen(SIDE_PROMPT))
        return False


def test_a_prompt_opening_inside_the_move_bar_is_not_answered(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    session = BarSession(["MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"])
    assert session.enter_move(timeout=5, answer_prompts=False) is False
    assert session.bar_calls == [("MOVE", False)]
    assert session.walk_prompt == SIDE_PROMPT
    assert session.events == []


def test_a_prompt_opening_inside_the_no_answer_is_not_answered(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    session = BarSession(["INTERESTED?  YES   NO"])
    assert session.enter_move(timeout=5, answer_prompts=False) is False
    assert session.bar_calls == [("NO", False)]
    assert session.walk_prompt == SIDE_PROMPT
    assert [e for e in session.events if e[0] in ("attach", "kernal")] == []


def test_press_bar_forwards_whether_a_prompt_may_be_answered():
    session = BarSession(["X"])
    session.opens_prompt = False
    session.press_bar("NO", answer_prompts=False)
    session.press_bar("NO")
    assert session.bar_calls == [("NO", False), ("NO", True)]


def test_a_prompt_that_appears_while_polling_the_move_ends_the_walk(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    clock = iter(range(1000))
    monkeypatch.setattr(C.time, "time", lambda: float(next(clock)))
    session = BarSession([MOVE_BAR, MOVE_BAR, SIDE_PROMPT])
    session.move_key = lambda *a, **k: session.events.append(("move", 0))
    session.live_triple = lambda: (5, 5, 0)
    assert session.walk_one("I", patience=500, answer_prompts=False) is False
    assert session.walk_prompt == SIDE_PROMPT
    assert session.walk_refused is None
    assert [e for e in session.events if e[0] in ("attach", "kernal")] == []


def test_a_failed_attach_does_not_hold_off_the_retry_for_the_same_disk(
        monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(C.time, "time", lambda: now[0])
    session = FakeSession(side=2)
    real_attach = session.attach

    def broken(path):
        session.attach = real_attach
        raise RuntimeError("the drive would not take it")

    session.attach = broken
    screen = SimpleNamespace(text=lambda: SIDE_PROMPT)
    with pytest.raises(RuntimeError):
        session.handle_prompt(screen)
    now[0] += 2.5
    assert session.handle_prompt(screen) is True
