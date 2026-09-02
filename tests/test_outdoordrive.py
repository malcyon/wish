"""Driving a party on the travel grid, where the driver used to know only the
dungeon.

Nothing here needs an emulator or a display.  The status lines are the two the
game actually draws -- `E 16:48 5,2` indoors and `OUTDOORS 22:02 7,28` on the
grid -- and the session is a fake that records the keys it was asked to send
and serves `$49E6`, `$49C0` and `$49C3` out of a dictionary.

The reason these are tests rather than notes is that all three faults in
`#189 (The emulator driver cannot move a party on the travel grid, and reads
its facing out of the word OUTDOORS)` were invisible from the outside: the
driver reported a facing, reported `moved=False`, and reported a square, and
every one of the three was wrong in a way that reads exactly like a save that
cannot walk.  An hour of `#50 (Lift the wilderness refusal from the DOS save
converter)`'s end-to-end proof went on it.
"""

import pathlib
import sys

# From this file, not from a path measured on somebody's machine -- the same
# lesson `tests/gamedata.py` and `tests/test_combatdrive.py` carry.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

from session import (  # noqa: E402
    COMBAT,
    COMPASS,
    DUNGEON,
    DUNGEON_XY,
    ENDED,
    INDOORS_AT,
    TRAVEL_XY,
    Session,
    Status,
    parse_status,
)

COLS = 40
ROWS = 25

#: The two status lines, verbatim.  The indoor one is off
#: `docs/70-driving-the-game.md`; the outdoor one is the frame driven on pool
#: slot 2 on 2026-09-02, `work/p50-outdoor/p50c-0I-menu.png`.
INDOOR_LINE = "E 16:48 5,2"
OUTDOOR_LINE = "OUTDOORS 22:02 7,28"

#: Row 24 on the travel grid while it waits for a direction, and the world
#: command bar it gives way to.
OUTDOOR_BAR = "1-8, RETURN OR BUTTON"
WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"


class FakeScreen:
    """A screen built from text rows, with the highlight on one word of one.

    `span_in` reads the snapshot's own colour RAM, so a bar with no colour on
    it is a bar `select_bar` can never walk a highlight along -- which is a
    fake that cannot be driven rather than a game that cannot be.
    """

    def __init__(self, rows: dict[int, str], highlight=None):
        self.codes = bytearray(0x20 for _ in range(ROWS * COLS))
        self.colours = bytearray(5 for _ in range(ROWS * COLS))
        for r, text in rows.items():
            for i, ch in enumerate(text[:COLS]):
                self.codes[r * COLS + i] = ord(ch)
        if highlight is not None:
            row, lo, hi = highlight
            for i in range(lo, hi + 1):
                self.colours[row * COLS + i] = 1

    def row(self, r: int) -> str:
        return "".join(chr(c) for c in self.codes[r * COLS:(r + 1) * COLS])

    def rows(self) -> list[str]:
        return [self.row(r) for r in range(ROWS)]

    def text(self) -> str:
        return "\n".join(self.rows())

    def contains(self, needle: str) -> bool:
        return needle.upper() in self.text().upper()


class FakeMonitor:
    """`Session.mon`'s contract, over a dictionary of bytes."""

    def __init__(self, memory):
        self.memory = memory

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, addr: int, length: int) -> bytes:
        return bytes(self.memory.get(addr + i, 0) for i in range(length))


class FakeKeyboard:
    """Records what was sent, and moves the fake game on when it should.

    A compass digit the fake has been told is walkable moves `$49C3`/`$49C4`
    and drops row 24 back to the world command bar, which is what the game
    does.  Any other key is recorded and changes nothing -- which is what
    pressing `I` out there does.
    """

    def __init__(self, session):
        self.session = session
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)
        self.session.pressed(name)

    def text(self, s, hold=0.0, gap=0.0):
        for ch in s:
            self.key(ch)


class FakeSession(Session):
    """A `Session` whose screen and memory come from this file.

    Everything that would touch VICE, X or a disk is replaced; everything
    under test -- `status`, `square`, `walk_one`, `walk_outdoors`,
    `outdoor_key`, `leave_outdoor_move` -- is the real code.
    """

    def __init__(self, bar: str = OUTDOOR_BAR, line: str = OUTDOOR_LINE,
                 indoors: bool = False, square=(7, 28), walkable=""):
        # No `Session.__init__`: it reads the environment and builds a real
        # Keyboard on a real X display.
        self.kbd = FakeKeyboard(self)
        self.bar = bar
        self.line = line
        self.memory = {INDOORS_AT: 1 if indoors else 0}
        self.put(TRAVEL_XY if not indoors else DUNGEON_XY, square)
        #: Which compass digits actually move the party here.  Everything
        #: else is a wall, which is a reading and not a failure.
        self.walkable = walkable
        self.said: list[str] = []

    # -- the fake game -----------------------------------------------------

    def put(self, addr, square):
        self.memory[addr] = square[0]
        self.memory[addr + 1] = square[1]

    def pressed(self, name: str) -> None:
        if name in self.walkable:
            dx, dy = COMPASS[name]
            here = self.square()
            self.put(TRAVEL_XY, (here[0] + dx, here[1] + dy))
            self.bar = WORLD_BAR
        elif name == "Return":
            # Return on the world bar takes whichever command the highlight is
            # on, which here is always MOVE and puts the direction prompt up;
            # Return at the direction prompt leaves it.
            self.bar = OUTDOOR_BAR if self.bar == WORLD_BAR else WORLD_BAR

    # -- the parts a walk touches -----------------------------------------

    def screen(self):
        # The highlight sits on the first word of row 24, which is MOVE on the
        # world bar -- the command every driver here asks for.
        first = self.bar.split(" ")[0]
        return FakeScreen({14: self.line, 24: self.bar},
                          (24, 0, len(first) - 1))

    def mon(self, timeout: float = 5.0):
        return FakeMonitor(self.memory)

    def handle_prompt(self, s=None):
        return False

    def log(self, *a):
        self.said.append(" ".join(str(x) for x in a))


# -- the status line, which has two shapes ---------------------------------


def test_the_travel_grid_status_line_answers_no_facing():
    """`OUTDOORS 22:02 7,28` -- the word where the facing letter goes.

    The old pattern took the final `S` of `OUTDOORS` and answered facing 2,
    south, for every outdoor party on every square.
    """
    at = parse_status(OUTDOOR_LINE)
    assert at == Status(None, 22 * 60 + 2, 7, 28)
    assert at.outdoors
    assert at.facing is None


def test_a_dungeon_status_line_still_reads_its_facing():
    assert parse_status(INDOOR_LINE) == Status(1, 16 * 60 + 48, 5, 2)
    assert not parse_status(INDOOR_LINE).outdoors


def test_no_letter_is_taken_out_of_the_middle_of_a_word():
    """The general form of the fault, not just the one word it was found in.

    Any word ending in N, E, S or W in front of a clock would have done it.
    """
    for word in ("OUTDOORS", "NORTHWEST", "GATEHOUSE"):
        at = parse_status(f"{word} 22:02 7,28")
        assert at is None or at.facing is None, word


def test_a_screen_with_no_status_line_answers_nothing():
    assert parse_status("LOAD SAVED GAME") is None


def test_the_reading_says_outdoors_in_words():
    """What a run prints.  `facing=2` was printed for years and was a guess."""
    assert parse_status(OUTDOOR_LINE).where() == "outdoors 22:02 7,28"
    assert parse_status(INDOOR_LINE).where() == "E 16:48 5,2"


def test_status_reads_the_travel_grid_line_off_the_screen():
    sess = FakeSession()
    assert sess.status() == Status(None, 22 * 60 + 2, 7, 28)


# -- which of the two worlds -----------------------------------------------


def test_the_square_comes_from_the_travel_pair_outdoors():
    """`$49C0` outdoors is the square the party left the grid on.

    It never moves however far the party walks, so a driver reading it
    concludes every outdoor step was blocked.
    """
    sess = FakeSession(square=(7, 28))
    sess.put(DUNGEON_XY, (15, 1))          # the pier, frozen since departure
    assert sess.indoors() is False
    assert sess.square() == (7, 28)


def test_the_square_comes_from_the_dungeon_triple_indoors():
    sess = FakeSession(bar=WORLD_BAR, line=INDOOR_LINE, indoors=True,
                       square=(5, 2))
    sess.put(TRAVEL_XY, (7, 28))           # stale since the party came inside
    assert sess.indoors() is True
    assert sess.square() == (5, 2)


# -- pressing a direction --------------------------------------------------


def test_a_move_on_the_travel_grid_presses_a_compass_digit():
    """`8` and `4` each moved the party a square; `I` moved it nothing."""
    sess = FakeSession(walkable="8")
    assert sess.walk_one("8") is True
    assert sess.kbd.sent[0] == "8"
    assert sess.square() == (6, 27)


def test_the_dungeons_letters_are_refused_on_the_travel_grid():
    """And refused **without pressing anything**.

    `I` is not a direction out there.  Sending it moved the party not at all
    while `walk_one` reported it blocked, which reads exactly like a save that
    cannot walk.
    """
    sess = FakeSession(walkable="8")
    assert sess.walk_one("I") is False
    assert sess.kbd.sent == []
    assert any("compass digit" in line for line in sess.said)


def test_a_move_outdoors_is_pressed_once_and_never_re_sent():
    """The fourth fault, which follows from the first two.

    `walk_one` re-sends a move up to four times until the status line changes,
    and out here a turn never changes it -- so one `K` became four presses and
    the party came back round to the heading it started on.  A blocked step is
    one press and a `False`.
    """
    sess = FakeSession(walkable="")         # every direction is a wall
    assert sess.walk_outdoors("3", patience=0.1) is False
    assert sess.kbd.sent.count("3") == 1


def test_the_direction_prompt_is_answered_without_asking_for_move():
    """A walked exit lands with `1-8, RETURN OR BUTTON` already up.

    `select_bar("MOVE")` finds no MOVE on that bar and spins to its timeout,
    which from the outside is indistinguishable from a party that cannot move.
    """
    sess = FakeSession(bar=OUTDOOR_BAR, walkable="3")
    assert sess.outdoor_key("3") is True
    assert sess.kbd.sent == ["3"]


def test_a_warped_arrival_takes_move_first():
    """The other half of it: a warp lands on the command bar and does need it."""
    sess = FakeSession(bar=WORLD_BAR, walkable="3")
    assert sess.outdoor_key("3") is True
    # `select_bar` presses Return on MOVE, which puts the direction prompt up;
    # the digit goes to that.
    assert sess.kbd.sent == ["Return", "3"]


def test_nothing_is_pressed_at_a_command_bar_to_leave_move():
    """Return at a world command bar runs whatever the highlight is on.

    `leave_move` presses before it looks, which is right in a dungeon -- the
    bar there reads `I,J,K,M` until the Return lands -- and wrong out here,
    where a step can have put the command bar back already.
    """
    sess = FakeSession(bar=WORLD_BAR)
    assert sess.leave_outdoor_move() is True
    assert sess.kbd.sent == []


def test_the_direction_prompt_is_left_with_a_return():
    sess = FakeSession(bar=OUTDOOR_BAR)
    assert sess.leave_outdoor_move() is True
    assert sess.kbd.sent == ["Return"]


# -- the callers that have to cope with an absent facing --------------------


class EndedFight(FakeSession):
    """A fight whose mode byte drops to DUNGEON on the first reading."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.reads = 0

    def mode(self):
        self.reads += 1
        return COMBAT if self.reads == 1 else DUNGEON

    def idle(self, seconds):
        pass


def test_a_fight_that_ends_on_the_travel_grid_is_seen_to_end():
    """`fight` waits for DUNGEON *and* a status line, and out there the line
    carries no facing letter.

    A pattern that wants one never matches, so the fight runs to the whole of
    its budget after it is over -- which for `savecheck --fight` is fifteen
    minutes of nothing.  This is the caller that the tightened pattern would
    have broken on its own; it goes red without the outdoor branch beside it.
    """
    sess = EndedFight(bar=WORLD_BAR, line=OUTDOOR_LINE)
    result = sess.fight(budget=5.0)
    assert result.outcome == ENDED
    assert result.seconds < 5.0
