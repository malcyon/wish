"""`Session.begin_adventuring` when the Return sent to BEGIN ADVENTURING is lost.

The session is a fake: the screen is a script that only moves when the code
under test sends a key through the keyboard buffer.
"""

import test_arrivalscene as base

Session = base.Session
FakeScreen = base.FakeScreen


class MenuScreen(FakeScreen):
    """The party menu, BEGIN ADVENTURING highlighted, on row 10."""

    def __init__(self):
        super().__init__("")
        text = "BEGIN ADVENTURING"
        for i, ch in enumerate(text):
            self.codes[10 * base.COLS + 4 + i] = ord(ch)
            self.colours[10 * base.COLS + 4 + i] = 1

    def highlighted_rows(self, colour=1, column=None):
        return [10]


class MenuAndDiskScreen(MenuScreen):
    """The menu still drawn, with a disk prompt over its bottom row."""

    def __init__(self):
        super().__init__()
        for i, ch in enumerate("INSERT SIDE # 3, AND PRESS ANY KEY."):
            self.codes[24 * base.COLS + i] = ord(ch)


class MovedMenuScreen(MenuScreen):
    def highlighted_rows(self, colour=1, column=None):
        return [11]


class DiskScreen(FakeScreen):
    def __init__(self):
        super().__init__("INSERT SIDE # 3, AND PRESS ANY KEY.")


class Fake(Session):
    def __init__(self, screens):
        self.screens = screens
        self.at = 0
        self.injected = []
        self.logged = []
        self.kbd = base.FakeKeyboard()
        self.here = "/nowhere"
        self.save_disk = "/nowhere/save.d64"

    def screen(self):
        return self.screens[self.at]

    def press_kernal(self, code):
        self.injected.append(code)
        self.at = min(self.at + 1, len(self.screens) - 1)

    def log(self, msg):
        self.logged.append(msg)

    def handle_prompt(self, s=None):
        return False

    def await_change(self, was, timeout=6.0, interval=0.4):
        return self.combat_state()

    def select_row(self, label, timeout=30.0, column=None):
        return True


def run(sess, **kw):
    return sess.begin_adventuring(resend_after=0.02, interval=0.005, **kw)


def test_a_dropped_return_is_resent_once_and_the_world_is_reached():
    sess = Fake([MenuScreen(), FakeScreen(base.WORLD_BAR)])
    sess.wait_for_world = lambda timeout=240.0, interval=0.35: True
    assert run(sess) is True
    assert sess.injected == [0x0D]
    assert len(sess.logged) == 1


def test_a_disk_prompt_gets_no_resend():
    sess = Fake([DiskScreen(), FakeScreen(base.WORLD_BAR)])
    sess.wait_for_world = lambda timeout=240.0, interval=0.35: True
    assert run(sess) is True
    assert sess.injected == []


def test_a_menu_that_never_changes_stops_at_the_bound_and_fails():
    sess = Fake([MenuScreen()])
    sess.press_kernal = lambda code: sess.injected.append(code)
    orig = sess.wait_for_world
    sess.wait_for_world = lambda timeout=240.0, interval=0.35: orig(0.1, 0.005)
    assert run(sess, max_resends=2) is False
    assert sess.injected == [0x0D, 0x0D]


def _no_resend(screens):
    sess = Fake(screens)
    sess.wait_for_world = lambda timeout=240.0, interval=0.35: True
    assert run(sess) is True
    assert sess.injected == []


def test_the_menu_with_a_disk_prompt_over_it_gets_no_resend():
    _no_resend([MenuAndDiskScreen()])


def test_a_moved_highlight_gets_no_resend():
    _no_resend([MovedMenuScreen()])


def test_a_message_screen_gets_no_resend():
    _no_resend([FakeScreen("THE PARTY IS LOADING")])


def test_the_world_bar_gets_no_resend():
    _no_resend([FakeScreen(base.WORLD_BAR)])


def test_a_screen_that_cannot_be_read_gets_no_resend():
    sess = Fake([None])
    reads = iter([None, None])
    sess.screen = lambda: next(reads, FakeScreen(base.WORLD_BAR))
    sess.wait_for_world = lambda timeout=240.0, interval=0.35: True
    sess.begin_adventuring(resend_after=0.02, interval=0.005, max_resends=3)
    assert sess.injected == []
