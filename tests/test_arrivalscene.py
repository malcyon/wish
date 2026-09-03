"""`Session.begin_adventuring` against an arrival that plays a scene first.

Nothing here needs an emulator or a display.  The session is a fake driven by
a script of row-24 bars, and what advances the script is the same thing that
advances the real game: a key sent, or `press_kernal` -- so nothing here
moves unless the code under test presses something.

`#182 (A driven save that arrives on a picture is reported as a failed load)`
is why this exists.  `begin_adventuring` used to wait only for `ENCAMP`, and
an arrival with a scene in front of it -- Sokol Keep's boat -- shows `PRESS
<RETURN> OR BUTTON TO CONTINUE` first and nothing in the old wait answered
it, so the game sat waiting on the driver while the driver sat waiting on the
game.  New Phlan and the Slums hand control straight back with no scene,
which is why every earlier driven save missed this.
"""

import importlib.util
import pathlib
import sys

# Before anything below touches `tools/`.  `tools/wish.py` is a plain module
# that happens to share the real `wish` *package*'s name, and once a bare
# `import wish` has resolved correctly it stays resolved: Python caches it in
# `sys.modules` and every later `import wish` anywhere in the process reuses
# that entry rather than searching `sys.path` again.  Importing the real
# package here, first, is what makes the rest of this file's `tools/` access
# safe regardless of what any other test file does with `sys.path` --
# `tests/test_debuglog.py`'s `from wish import backends`, collected long
# after this file, failed with `cannot import name 'backends' from 'wish'`
# until this line was added (#182).
import wish  # noqa: F401,E402

_TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"


def _load_tools_module(name: str):
    """Import a `tools/` module by its file path, and leave `sys.path`
    exactly as this function found it.

    `tools/session.py` needs its siblings (`instance`, `drive`) importable
    by their bare names, and does its own `sys.path.insert(0, ...)` to get
    them, so `tools/` still has to be on `sys.path` for the moment
    `exec_module` runs -- but only for that moment.  Several other test
    files leave `tools/` on `sys.path` permanently to reach `session`; this
    one does not, so nothing collected afterwards can be shadowed by it.
    """
    added = str(_TOOLS) not in sys.path
    if added:
        sys.path.insert(0, str(_TOOLS))
    try:
        spec = importlib.util.spec_from_file_location(name, _TOOLS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            # A module that failed half way through must not stay cached, or
            # the next plain `import session` anywhere in this process gets
            # the broken object instead of a fresh ImportError. Raised in the
            # code review of #182.
            sys.modules.pop(name, None)
            raise
        return module
    finally:
        if added:
            sys.path[:] = [p for p in sys.path if p != str(_TOOLS)]


Session = _load_tools_module("session").Session

COLS, ROWS = 40, 25

PRESS_BAR = "PRESS <RETURN> OR BUTTON TO CONTINUE"
WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"


class FakeScreen:
    """One row-24 bar, on an otherwise blank screen."""

    def __init__(self, bar: str):
        self.codes = bytearray(0x20 for _ in range(ROWS * COLS))
        for i, ch in enumerate(bar[:COLS]):
            self.codes[24 * COLS + i] = ord(ch)

    def row(self, r: int) -> str:
        return "".join(chr(c) for c in self.codes[r * COLS:(r + 1) * COLS])

    def rows(self) -> list[str]:
        return [self.row(r) for r in range(ROWS)]

    def text(self) -> str:
        return "\n".join(self.rows())

    def find(self, needle: str):
        needle = needle.upper()
        for r, line in enumerate(self.rows()):
            c = line.find(needle)
            if c >= 0:
                return r, c
        return None

    def contains(self, needle: str) -> bool:
        return self.find(needle) is not None


class FakeKeyboard:
    """Records what was sent.  `begin_adventuring` should not need this at
    all for the continue prompt -- that goes through `press_kernal`, the same
    way `fight`'s own `BAR_PRESS` branch answers one, because XTEST Return is
    not dependable at a prompt and the keyboard buffer is."""

    def __init__(self):
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)

    def text(self, s, hold=0.0, gap=0.0):
        for ch in s:
            self.key(ch)


class FakeSession(Session):
    """A `Session` whose screen comes from a script of row-24 bars.

    Everything that would touch VICE, X or a disk is replaced; `wait_for_world`
    and `begin_adventuring` are the real code.
    """

    def __init__(self, bars: list[str]):
        # No `Session.__init__`: it reads the environment and opens a real
        # keyboard on a real X display.
        self.bars = list(bars)
        self.kbd = FakeKeyboard()
        self.injected: list[int] = []
        self.at = 0

    def step(self) -> None:
        self.at = min(self.at + 1, len(self.bars) - 1)

    def screen(self):
        return FakeScreen(self.bars[self.at])

    def press_kernal(self, code: int) -> None:
        self.injected.append(code)
        self.step()

    def handle_prompt(self, s=None) -> bool:
        return False

    def select_row(self, label: str, timeout: float = 30.0,
                   column: int | None = None) -> bool:
        return True   # BEGIN ADVENTURING's own menu is not what this tests


def test_an_arrival_with_a_scene_still_reaches_the_world_bar():
    """Sokol Keep's boat: the scene stalls at a continue prompt, and nothing
    but pressing Return there ever shows `ENCAMP`.

    This fixture's bar never changes on its own -- only `press_kernal`
    advances it -- so the old shape (`wait_text("ENCAMP", 240)`, watching for
    one thing and never answering the prompt) times out here rather than
    reaching the world.  Reverting `Session.begin_adventuring` to that shape
    makes this answer False instead of True.
    """
    sess = FakeSession([PRESS_BAR, WORLD_BAR])
    assert sess.begin_adventuring() is True
    assert 0x0D in sess.injected
    assert sess.kbd.sent == []


def test_new_phlan_and_the_slums_still_hand_control_straight_back():
    """No scene in front of it: `ENCAMP` is already on the first screen, so
    nothing should be pressed at all."""
    sess = FakeSession([WORLD_BAR])
    assert sess.begin_adventuring() is True
    assert sess.injected == []


def test_wait_for_world_gives_up_rather_than_waiting_for_ever():
    """A bar that is neither the world's nor a continue prompt -- `GUARDING`,
    read off a live screen in `work/p118-step3/` -- still gives up inside its
    own timeout instead of hanging."""
    sess = FakeSession(["GUARDING"])
    assert sess.wait_for_world(timeout=0.2, interval=0.02) is False

