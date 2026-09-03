"""Reaching every character's sheet in a driven session, not only the first.

Nothing here needs an emulator or a display.  The game is a fake screen that
behaves the way the real one was measured to behave on pool slot 0 against
`PORSAVE13.D64` on 2026-09-03, for
`#183 (Nothing knows how to reach the other five character sheets in a driven
session)`:

* the world screen's party panel draws one name in the highlight colour and
  the rest in cyan, and `Up` and `Down` move that highlight, wrapping;
* `VIEW` on the world bar puts up the sheet of whoever the panel is
  highlighting;
* the sheet's own bar is `VIEW:ITEMS EXIT`.  `Up`, `Down`, `N`, `P`, `+`,
  `-`, `>`, `<`, Tab, the function keys and the digits `1`-`6` were all
  pressed at a live one and **not one of them changed character**, so the
  fake ignores them too;
* the sheet's highlight starts on `ITEMS`, and `ITEMS` opens the item list
  that re-arms itself -- so pressing Return without walking the highlight to
  `EXIT` is a way into a screen a driven run does not get out of.

The reason these are tests is that `tools/savecheck.py` used to step the
party with a `NEXT` that is not on the bar, so every run it drove read the
first character's sheet and nothing else -- and the faults this project has
actually shipped, an armour class of 9 displayed as 51, a dropped combat tail
and a garbage weapon line, are all things only a sheet shows.
"""

from conftest import load_tools_module

S = load_tools_module("session")
Session = S.Session

COLS, ROWS = 40, 25

NAMES = ["BRUTUS", "MAGNUS", "SILAS", "ROLAND", "LADY KATHERINE", "MALCYON"]
WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
SHEET_BAR = "VIEW:ITEMS EXIT"
ITEMS_BAR = "READY TRADE DROP EXIT"

#: What the panel draws the unselected names in.  Cyan, measured; anything
#: that is not the highlight colour would do.
CYAN = 3


class FakeScreen:
    """Screen codes and colour RAM, which is what the drivers read."""

    def __init__(self):
        self.codes = bytearray(0x20 for _ in range(ROWS * COLS))
        self.colours = bytearray(2 for _ in range(ROWS * COLS))

    def put(self, r: int, c: int, text: str, colour: int = 5) -> None:
        for i, ch in enumerate(text):
            self.codes[r * COLS + c + i] = ord(ch)
            self.colours[r * COLS + c + i] = colour

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
    def __init__(self, game):
        self.game = game
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)
        self.game.press(name)

    def text(self, s, hold=0.0, gap=0.0):
        for ch in s:
            self.key(ch)

    def screenshot(self, path):
        self.game.shots.append(path)
        return True


class FakeGame(Session):
    """A `Session` whose screen is the world panel and the sheet it opens.

    Everything that would touch VICE, X or a disk is replaced; `select_bar`,
    `select_party`, `party_rows`, `party_highlight` and `character_sheet` are
    the real code.
    """

    def __init__(self, names=NAMES, status_row: int | None = 14):
        # No `Session.__init__`: it reads the environment and opens a real
        # keyboard on a real X display.
        self.names = list(names)
        self.status_row = status_row
        self.picked = 0        # which name the panel highlights
        self.where = "world"
        self.bar_at = 0        # which word of the current bar is highlighted
        self.kbd = FakeKeyboard(self)
        self.shots: list[str] = []

    # -- what the screen looks like ---------------------------------------

    def bar(self) -> str:
        return {"world": WORLD_BAR, "sheet": SHEET_BAR,
                "items": ITEMS_BAR}[self.where]

    def words(self) -> list[tuple[int, str]]:
        """Each command on the current bar, with the column it starts in."""
        out, col = [], 0
        for word in self.bar().split(" "):
            if word:
                out.append((col, word))
            col += len(word) + 1
        return out

    def screen(self):
        s = FakeScreen()
        if self.where == "world":
            s.put(2, S.PARTY_COLUMN, "NAME            AC HP", 1)
            for i, name in enumerate(self.names):
                s.put(4 + i, S.PARTY_COLUMN, f"{name:<16}2 11",
                      1 if i == self.picked else CYAN)
            if self.status_row is not None:
                # The line that would be read as one more character if the
                # panel were taken as "every non-blank row under the header".
                s.put(self.status_row, S.PARTY_COLUMN, "W 21:15 15,4")
        else:
            # Column 1, behind the panel frame, as the live sheet draws it.
            s.put(1, 1, self.names[self.picked], 3)
            s.put(17, 1, "AC 2")
        col, word = self.words()[self.bar_at]
        s.put(24, 0, self.bar())
        s.put(24, col, word, 1)
        return s

    # -- what the keys do --------------------------------------------------

    def press(self, name: str) -> None:
        words = self.words()
        if name == "Right":
            self.bar_at = min(self.bar_at + 1, len(words) - 1)
        elif name == "Left":
            self.bar_at = max(self.bar_at - 1, 0)
        elif name in ("Down", "Up") and self.where == "world":
            step = 1 if name == "Down" else -1
            self.picked = (self.picked + step) % len(self.names)
        elif name == "Return":
            chosen = words[self.bar_at][1]
            if self.where == "world" and chosen == "VIEW":
                self.where, self.bar_at = "sheet", 1   # starts on ITEMS
            elif self.where == "sheet" and chosen == "EXIT":
                self.where = "world"
                self.bar_at = [w for _, w in self.words()].index("VIEW")
            elif self.where == "sheet" and chosen == "VIEW:ITEMS":
                self.where, self.bar_at = "items", 0
            elif self.where == "items":
                # The list that re-arms itself: its own EXIT returns to the
                # bar and the next Return drops straight back in.  Nothing a
                # driven run does gets out of here.
                self.bar_at = 0
        # Everything else -- N, P, +, -, >, <, Tab, F1-F7, the digits, and
        # Up/Down on the sheet -- was pressed at a live sheet and did nothing.

    # -- the parts of Session that would talk to hardware -------------------

    def handle_prompt(self, s=None) -> bool:
        return False

    def leave_move(self, tries: int = 8) -> bool:
        return False


def test_every_character_in_the_party_has_a_sheet_read():
    """The whole of `#183`.  Six slots asked for, six different names back.

    Neuter `Session.select_party` to `return True` -- which is what a driver
    that never moves the panel highlight amounts to -- and this reads
    `BRUTUS` six times and fails on the second slot.
    """
    game = FakeGame()
    # The sheet's name row starts one column in, behind the frame character,
    # exactly as the live screen draws it -- so the name is read out of the
    # line rather than compared to the whole of it.
    got = [game.character_sheet(n)[0].strip() for n in range(len(NAMES))]
    assert got == NAMES


def test_the_panel_is_the_selector_and_view_shows_whoever_it_highlights():
    game = FakeGame()
    assert game.select_party(3) is True
    assert game.party_highlight() == 3
    assert game.character_sheet()[0].strip() == "ROLAND"


def test_the_highlight_is_walked_the_short_way_and_never_round_the_wrap():
    """`Down` past the last name wraps to the first -- measured live -- and
    `select_party` deliberately does not use that.

    It walks whichever way is shorter *inside* the list, so it needs only
    that `Up` and `Down` move one row, which both were seen to do.  Whether
    `Up` wraps at the top was never measured, and a driver that counted on it
    would be resting on an untested key."""
    game = FakeGame()
    assert game.select_party(5) is True
    assert game.kbd.sent == ["Down"] * 5
    game.kbd.sent.clear()
    assert game.select_party(1) is True
    assert game.kbd.sent == ["Up"] * 4


def test_a_sheet_is_left_by_exit_and_never_by_returning_on_items():
    """The sheet's highlight starts on `ITEMS`, and `ITEMS` is a one-way door.

    A driver that pressed Return where the highlight already was would open
    the item list and never come back, so the check is that the run ends at
    the world bar with the item list never entered.
    """
    game = FakeGame()
    game.character_sheet(2)
    assert game.where == "world"
    assert game.bar() == WORLD_BAR


def test_the_status_line_is_not_counted_as_a_seventh_character():
    """`W 21:15 15,4` starts in the panel's own name column, two rows under
    the last name.  Counting every non-blank row under the header would make
    a party of six read as seven -- which is the number `#104` turns on."""
    game = FakeGame()
    assert len(game.party_rows()) == 6
    game.status_row = None
    assert len(game.party_rows()) == 6


def test_a_party_of_eight_is_read_as_eight():
    """A C64 save holds eight, and eight names fill rows 4 to 11 -- the last
    row `PANEL_ROWS` covers."""
    eight = NAMES + ["THRENDER GRONE", "TARL"]
    game = FakeGame(names=eight, status_row=None)
    assert len(game.party_rows()) == 8
    assert game.character_sheet(7)[0].strip() == "TARL"


def test_asking_for_a_slot_the_party_does_not_have_is_refused():
    game = FakeGame()
    assert game.select_party(6) is False
    assert game.character_sheet(6) is None


def test_a_sheet_is_photographed_while_it_is_still_up():
    """`character_sheet` leaves the sheet before it returns, so the caller
    cannot take that picture itself -- which is why it takes a `shot`."""
    game = FakeGame()
    game.character_sheet(1, shot="/tmp/nowhere-magnus.png")
    assert game.shots == ["/tmp/nowhere-magnus.png"]
