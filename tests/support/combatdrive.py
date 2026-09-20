"""Helpers `test_combatdrive` shares with the test files that reuse them."""

from conftest import load_tools_module

session = load_tools_module("session")


COMBAT = session.COMBAT
DUNGEON = session.DUNGEON


Session = session.Session


word_column = session.word_column


COLS = 40
ROWS = 25


class FakeScreen:
    """A screen built from text rows, with a highlight run on one of them.

    `codes` are ASCII rather than the game's screen codes, which is all
    `span_in` needs of them: it only asks whether a cell is blank.
    """

    def __init__(self, rows: dict[int, str], highlight=None, colour: int = 1):
        self.codes = bytearray(0x20 for _ in range(ROWS * COLS))
        self.colours = bytearray(5 for _ in range(ROWS * COLS))
        for r, text in rows.items():
            for i, ch in enumerate(text[:COLS]):
                self.codes[r * COLS + i] = ord(ch)
        if highlight is not None:
            row, lo, hi = highlight
            for i in range(lo, hi + 1):
                self.colours[row * COLS + i] = colour

    def row(self, r: int) -> str:
        return "".join(chr(c) for c in self.codes[r * COLS:(r + 1) * COLS])

    def rows(self) -> list[str]:
        return [self.row(r) for r in range(ROWS)]

    def text(self) -> str:
        return "\n".join(self.rows())


def bar_screen(bar: str, highlight=None) -> FakeScreen:
    return FakeScreen({24: bar}, highlight)


def command_bar(bar: str, label: str) -> FakeScreen:
    """A command bar with the highlight sitting on `label`."""
    col = word_column(bar, label)
    assert col >= 0, f"{label} is not a word on {bar!r}"
    return bar_screen(bar, (24, col, col + len(label) - 1))


class FakeKeyboard:
    """Records what was sent, and moves the scripted game on a frame.

    The game advances because something was done to it -- a key, an injected
    Return, or time passing while a monster takes its turn -- and all three
    are seams here.
    """

    def __init__(self, session):
        self.session = session
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)
        self.session.step()

    def text(self, s, hold=0.0, gap=0.0):
        for ch in s:
            self.key(ch)


class FakeSession(Session):
    """A `Session` whose screen and mode byte come from a script.

    Everything that would touch VICE, X or the disk is replaced; everything
    being tested -- `combat_state`, `combat_bar`, `fight` -- is the real code.
    """

    def __init__(self, frames):
        # No `Session.__init__`: it reads the environment and builds a real
        # Keyboard.  Only the attributes the combat code uses are set.
        self.frames = list(frames)          # (mode, screen) in order
        self.kbd = FakeKeyboard(self)
        self.injected: list[int] = []
        self.at = 0

    def step(self):
        self.at = min(self.at + 1, len(self.frames) - 1)

    # -- the parts a fight touches ---------------------------------------
    def screen(self):
        return self.frames[self.at][1]

    def mode(self):
        return self.frames[self.at][0]

    def press_kernal(self, code):
        self.injected.append(code)
        self.step()

    def idle(self, seconds):
        self.step()

    def handle_prompt(self, s=None):
        return False


STATUS = "S 10:56 14,5"
