"""`Session.boot` must get past VICE's own error dialog and say what it saw when it gives up.

No emulator: the nested display, the keyboard and the screen are fakes.  A modal
GTK dialog grabs the keyboard, so a key sent while one is up never reaches the
C64 and a boot dies waiting for a menu it was never able to answer.
"""

import pathlib
import re
import threading

from conftest import load_tools_module

session = load_tools_module("session")

FASTLOADER_DOC = pathlib.Path(__file__).resolve().parents[2] / "docs" / "131-fastloader.md"


class FakeDisplay:
    """The windows on a nested display and the keys the watchdog sent them."""

    def __init__(self, names):
        self.windows = dict(enumerate(names, start=1))
        self.keys = []

    def xdo(self, display, *args):
        if args[0] == "search":
            return " ".join(str(w) for w in self.windows)
        if args[0] == "getwindowname":
            return self.windows[int(args[1])]
        if args[0] == "key":
            self.keys.append(args[1])
            # Return closes the one dialog that holds the keyboard grab
            gone = next((w for w, n in self.windows.items() if "Error" in n), None)
            self.windows.pop(gone, None)
        return ""

    @property
    def dialog_up(self):
        return any("Error" in n for n in self.windows.values())


class FakeScreen:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text

    def contains(self, needle):
        return needle in self._text

    def rows(self):
        return self._text.split("\n")


class FakeKeyboard:
    def __init__(self):
        self.pressed = []
        self.shots = []

    def key(self, name, *a):
        self.pressed.append(name)

    def screenshot(self, path):
        self.shots.append(path)
        return True


def _session(tmp_path, monkeypatch, display, after_fastloader=None):
    """A session whose screen is what the game shows for the keys pressed so far.

    Nothing is readable while a dialog is up, because the emulator is not being
    driven: the C64's own screen only advances when a key reaches it.
    """
    sess = session.Session()
    sess.here = str(tmp_path)
    sess.kbd = FakeKeyboard()
    monkeypatch.setattr(session, "_xdo", display.xdo)
    monkeypatch.setattr(session.Session, "DIALOG_POLL", 0.01)
    monkeypatch.setattr(session.Session, "DIALOG_SETTLE", 0.0)
    monkeypatch.setattr(sess, "launch", lambda: None)
    monkeypatch.setattr(sess, "pass_protection", lambda: True)
    monkeypatch.setattr(sess, "log", lambda *a: None)

    stages = ["DISABLE FASTLOADER (Y/N)?",
              after_fastloader or "PLAY GAME",
              "INPUT THE CODE WORD"]

    def screen():
        if display.dialog_up:
            return None
        return FakeScreen(stages[min(len(sess.kbd.pressed), len(stages) - 1)])

    monkeypatch.setattr(sess, "screen", screen)
    return sess


def test_a_dialog_that_appears_during_the_wait_is_dismissed(tmp_path, monkeypatch):
    display = FakeDisplay(["VICE (C64SC)", "VICE Error"])
    sess = _session(tmp_path, monkeypatch, display)

    assert sess.boot() is True

    assert display.keys == ["Return"]
    # the game got the answer and the menu's Return, and nothing else
    assert sess.kbd.pressed == ["y", "Return"]
    assert not [t for t in threading.enumerate() if t.name == "vice-dialogs"]


def test_no_key_is_pressed_into_the_game_when_no_dialog_is_up(tmp_path, monkeypatch):
    display = FakeDisplay(["VICE (C64SC)"])
    sess = _session(tmp_path, monkeypatch, display)

    assert sess.boot() is True

    assert display.keys == []
    assert sess.kbd.pressed == ["y", "Return"]


def test_the_watchdog_presses_return_once_per_dialog(monkeypatch):
    display = FakeDisplay(["VICE (C64SC)", "VICE Error", "VICE Error"])
    monkeypatch.setattr(session, "_xdo", display.xdo)
    monkeypatch.setattr(session.time, "sleep", lambda s: None)

    class Ticks:
        """`stop.wait` for three polls, then stop."""

        def __init__(self):
            self.left = 3

        def wait(self, interval):
            self.left -= 1
            return self.left < 0

    session.dismiss_dialogs(":9", Ticks(), 0.0)

    assert display.keys == ["Return", "Return"]
    assert not display.dialog_up


def _stock_times():
    """The stock-kernal `M2 -> M5` times in `docs/131-fastloader.md`'s first table."""
    rows = re.findall(r"^\| stock [^|]*\|[^|]*\| \**([\d.]+) s\**", FASTLOADER_DOC.read_text(),
                      re.M)
    return [float(r) for r in rows]


def test_the_play_game_wait_covers_the_measured_stock_boot_twice_over():
    stock = _stock_times()
    assert sorted(stock) == [199.6, 238.6], "the doc's table has moved; re-read it"
    # Twice the slowest, because a second emulator on the machine cost more
    # than 240 s minus the 204 s measured alone, and a failing boot only costs
    # the wait when VICE is still alive.
    assert session.PLAY_GAME_WAIT >= 2 * max(stock)


def test_a_timeout_says_what_the_screen_showed(tmp_path, monkeypatch):
    display = FakeDisplay(["VICE (C64SC)", "VICE Error"])
    sess = _session(tmp_path, monkeypatch, display,
                    after_fastloader="LOADING THE WRONG THING\nSECOND LINE")
    monkeypatch.setattr(session, "PLAY_GAME_WAIT", 0.05)
    said = []
    monkeypatch.setattr(sess, "log", lambda *a: said.append(" ".join(map(str, a))))

    assert sess.boot() is False

    message = sess.boot_failure
    assert "PLAY GAME" in message
    assert "LOADING THE WRONG THING" in message and "SECOND LINE" in message
    assert sess.kbd.shots and sess.kbd.shots[0] in message
    assert any("LOADING THE WRONG THING" in line for line in said)


def test_a_timeout_with_no_readable_screen_still_says_so(tmp_path, monkeypatch):
    display = FakeDisplay(["VICE (C64SC)", "VICE Error", "VICE Error"])
    sess = _session(tmp_path, monkeypatch, display)
    monkeypatch.setattr(session, "_xdo", lambda d, *a: "")   # the dialog is never answered
    monkeypatch.setattr(session, "FASTLOADER_WAIT", 0.05)

    assert sess.boot() is False

    assert "no fastloader prompt" in sess.boot_failure
    assert "no readable text screen" in sess.boot_failure
