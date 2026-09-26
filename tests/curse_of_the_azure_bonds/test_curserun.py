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
    now[0] += 0.35
    assert not session.handle_prompt(screen)
    now[0] += 8.5
    assert session.handle_prompt(screen)
    assert [e for e in session.events if e[0] == "kernal"] == [("kernal", 0x20)] * 2
