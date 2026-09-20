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
    # Twice the slowest, so a second emulator on the machine slowing the boot
    # past 240 s still fits; a failing boot only costs the wait when VICE is
    # still alive.
    assert session.PLAY_GAME_WAIT >= 2 * max(stock)


class FakeGame:
    """A C64 whose screen moves only for the keys that actually reached it.

    The text screen is read through the monitor, so it stays readable whatever
    is on the nested display; a key is not, because a modal dialog's keyboard
    grab takes it first.  `deaf` is how many XTEST keys the game swallows
    before it starts reading -- one, at a screen it has just drawn, is the
    ordinary case `drive.wait_for` already warns about.
    """

    def __init__(self, display, deaf: int = 0):
        self.display = display
        self.deaf = deaf
        self.stages = ["POOL OF RADIANCE / DISABLE FASTLOADER (Y/N) ?",
                       "POOL OF RADIANCE / DISABLE FASTLOADER (Y/N) ?YES",
                       "PLAY GAME",
                       "INPUT THE CODE WORD"]
        self.at = 0
        self.sent: list[str] = []      # sent over XTEST, grabbed or not
        self.got: list[str] = []       # what the C64 saw
        self.shots: list[str] = []

    def key(self, name, *a):
        self.sent.append(name)
        if self.display.dialog_up:
            return                     # the dialog's grab eats it
        if self.deaf > 0:
            self.deaf -= 1
            return
        self._take(name)

    def kernal(self, code):
        self._take(f"kernal:{code:02X}")   # no X grab can swallow this one

    def _take(self, what):
        self.got.append(what)
        self.at = max(self.at, 1)      # the prompt echoes the answer

    def screenshot(self, path):
        self.shots.append(path)
        return True

    def screen(self):
        """What the monitor would read, and the load running on by itself.

        Only the answer needs a key here: everything after it is a load, and a
        stage that waited for one would make these tests about the menu keys
        rather than about the answer.
        """
        text = self.stages[self.at]
        if self.at:
            self.at = min(self.at + 1, len(self.stages) - 1)
        return FakeScreen(text)


def _racing_session(tmp_path, monkeypatch, display, game):
    """A session driving `game`, with the dialog watchdog too slow to help.

    `DIALOG_POLL` of 30 s is this machine: the prompt is up about two seconds
    after VICE is, and the watchdog's first look comes later than the answer.
    """
    sess = session.Session()
    sess.here = str(tmp_path)
    sess.kbd = game
    monkeypatch.setattr(session, "_xdo", display.xdo)
    monkeypatch.setattr(session, "ANSWER_RESEND", 0.05)
    monkeypatch.setattr(session, "PLAY_GAME_WAIT", 1.0)
    monkeypatch.setattr(session.Session, "DIALOG_POLL", 30.0)
    monkeypatch.setattr(session.Session, "DIALOG_SETTLE", 0.0)
    monkeypatch.setattr(sess, "launch", lambda: None)
    monkeypatch.setattr(sess, "pass_protection", lambda: True)
    monkeypatch.setattr(sess, "log", lambda *a: None)
    monkeypatch.setattr(sess, "screen", game.screen)
    monkeypatch.setattr(sess, "press_kernal", game.kernal)
    return sess


def test_the_boot_closes_vices_dialog_before_it_answers_the_fastloader(tmp_path,
                                                                      monkeypatch):
    display = FakeDisplay(["VICE (C64SC)", "VICE Error"])
    game = FakeGame(display)
    sess = _racing_session(tmp_path, monkeypatch, display, game)

    assert sess.boot() is True

    # the boot pressed Return at the dialog itself rather than waiting for the
    # watchdog, so the very first `y` reached the game
    assert display.keys == ["Return"]
    assert game.got[0] == "y"


def test_the_fastloader_answer_is_sent_again_when_the_game_did_not_take_it(
        tmp_path, monkeypatch):
    display = FakeDisplay(["VICE (C64SC)"])
    game = FakeGame(display, deaf=1)
    sess = _racing_session(tmp_path, monkeypatch, display, game)

    assert sess.boot() is True

    assert game.sent[:2] == ["y", "y"], "the swallowed answer was never sent again"
    assert game.got[0] == "y"


def test_an_answer_xtest_never_delivers_goes_through_the_kernal_buffer(tmp_path,
                                                                      monkeypatch):
    display = FakeDisplay(["VICE (C64SC)"])
    game = FakeGame(display, deaf=99)          # XTEST never arrives at all
    sess = _racing_session(tmp_path, monkeypatch, display, game)

    assert sess.boot() is True

    assert game.sent == ["y"] * (session.ANSWER_TRIES - 1) + ["Return"]
    assert game.got[0] == "kernal:59"          # PETSCII `Y`


def test_a_fastloader_prompt_that_takes_no_answer_at_all_is_reported(tmp_path,
                                                                    monkeypatch):
    display = FakeDisplay(["VICE (C64SC)"])
    game = FakeGame(display, deaf=99)
    sess = _racing_session(tmp_path, monkeypatch, display, game)
    monkeypatch.setattr(sess, "press_kernal", lambda code: None)

    assert sess.boot() is False

    assert "the fastloader prompt took no answer" in sess.boot_failure
    assert "DISABLE FASTLOADER" in sess.boot_failure


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


def _watchers():
    return [t for t in threading.enumerate() if t.name == "vice-dialogs" and t.is_alive()]


def test_a_boot_inside_an_outer_watch_starts_no_second_watcher(tmp_path, monkeypatch):
    display = FakeDisplay(["VICE (C64SC)"])
    sess = _session(tmp_path, monkeypatch, display)
    during = []
    real_screen = sess.screen

    def counting_screen():
        during.append(len(_watchers()))
        return real_screen()

    monkeypatch.setattr(sess, "screen", counting_screen)

    with sess.watching_dialogs():
        assert sess.boot() is True
        assert len(_watchers()) == 1, "the inner boot stopped the outer watcher"

    assert during and set(during) == {1}, "a second watcher ran during the boot"
    assert not _watchers()


def test_a_watcher_thread_that_cannot_start_does_not_leak_the_count(tmp_path,
                                                                   monkeypatch):
    display = FakeDisplay(["VICE (C64SC)"])
    sess = _session(tmp_path, monkeypatch, display)
    real_thread = threading.Thread

    class CannotStart(real_thread):
        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(session.threading, "Thread", CannotStart)
    try:
        with sess.watching_dialogs():
            raise AssertionError("the block ran with no watcher")
    except RuntimeError as e:
        assert "can't start" in str(e)
    assert sess._dialog_watchers == 0

    monkeypatch.setattr(session.threading, "Thread", real_thread)
    with sess.watching_dialogs():
        assert len(_watchers()) == 1, "no later watcher started"
    assert not _watchers()


def test_a_boot_with_no_xdotool_fails_and_says_so_instead_of_raising(tmp_path,
                                                                     monkeypatch):
    display = FakeDisplay(["VICE (C64SC)"])
    sess = _session(tmp_path, monkeypatch, display)

    def no_xdotool(display, *args):
        raise FileNotFoundError("xdotool")

    monkeypatch.setattr(session, "_xdo", no_xdotool)
    monkeypatch.setattr(sess, "screen", lambda: FakeScreen("LOADING"))
    monkeypatch.setattr(session, "FASTLOADER_WAIT", 0.05)

    def no_import(path):
        raise FileNotFoundError("import")

    monkeypatch.setattr(sess.kbd, "screenshot", no_import)

    assert sess.boot() is False

    assert "no fastloader prompt" in sess.boot_failure
    assert "(unavailable: xdotool)" in sess.boot_failure
    assert "(unavailable: import)" in sess.boot_failure
    assert not _watchers()


def test_a_fastloader_prompt_answered_with_no_xdotool_fails_and_says_so(
        tmp_path, monkeypatch):
    """The prompt appears, so the boot goes to close VICE's dialog and cannot."""
    display = FakeDisplay(["VICE (C64SC)"])
    sess = _session(tmp_path, monkeypatch, display)

    def no_xdotool(display, *args):
        raise FileNotFoundError("xdotool")

    monkeypatch.setattr(session, "_xdo", no_xdotool)

    assert sess.boot() is False

    assert "xdotool" in sess.boot_failure
    assert "fastloader" in sess.boot_failure
    assert sess.kbd.pressed == [], "no answer was sent into a game with no way to look"
    assert not _watchers()


def test_the_dialog_watcher_says_once_and_ends_when_xdotool_is_missing(monkeypatch):
    def no_xdotool(display, *args):
        raise FileNotFoundError("xdotool")

    said = []
    monkeypatch.setattr(session, "_xdo", no_xdotool)
    monkeypatch.setattr(session.Session, "log", staticmethod(lambda *a: said.append(a)))

    class Ticks:
        def wait(self, interval):
            return False            # never stopped: only the error can end the loop

    session.dismiss_dialogs(":9", Ticks(), 0.0)

    assert len(said) == 1 and "xdotool" in said[0][0]


def test_a_failed_code_word_patch_is_a_boot_failure_with_a_reason(tmp_path,
                                                                 monkeypatch):
    display = FakeDisplay(["VICE (C64SC)"])
    sess = _session(tmp_path, monkeypatch, display)
    monkeypatch.setattr(sess, "pass_protection", lambda: False)

    assert sess.boot() is False

    assert "$12D9" in sess.boot_failure
