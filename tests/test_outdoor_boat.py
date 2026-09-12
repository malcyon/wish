"""A boat landing's question is not a wall, and the driver used to call it one.

`#382 (An outdoor Pool of Radiance party's compass step is refused, and the
retry cannot find the movement prompt afterwards)`.  The converted Amiga party
of `#376 (An Amiga party on the travel grid still cannot be converted to the
C64 or DOS, because the reader refuses one)` stands on the west landing it
sailed to.  Choosing `MOVE` there does not put up `1-8, RETURN OR BUTTON`; it
puts up a picture of a boat, *"THERE IS A BOAT HERE THAT WILL TAKE YOU BACK TO
THE CIVILISED SECTION OF PHLAN.  WILL YOU TAKE IT?"*, and the bar `TAKE BOAT
STAY`.

`outdoor_key` pressed the digit six tenths of a second after selecting `MOVE`,
without looking at what row 24 had become, so eight directions in a row went
into the boat's own question and eight steps were recorded as blocked -- a map
fact nobody had measured.  Watched on pool slot 0, 2026-09-07, with
`#190 (A C64 party standing on the travel grid cannot be written into a DOS
save)`'s engine-written outdoor save walking four of four on the next slot at
the same moment.

Nothing here needs an emulator: `BoatSession` is a `Session` whose screen and
bars are fixed answers, so what is under test is what the driver does with a
row 24 it did not expect.
"""

from conftest import load_tools_module

from goldbox import c64_port as G

S = load_tools_module("session")

#: Row 24 on the landing square, and row 24 when the game is ready for a
#: direction.  Both read off the running machine.
BOAT_ROW = "TAKE BOAT STAY" + " " * 26
PROMPT_ROW = "1-8, RETURN OR BUTTON" + " " * 19
WORLD_ROW = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK  "


class FakeKeyboard:
    def __init__(self):
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)


class BoatSession(S.Session):
    """The world bar, then the boat's question, and never the `1-8` prompt.

    `rows` is what row 24 reads on each successive look, which is how the
    landing square actually behaves: the command bar, then -- once `MOVE` has
    been taken -- the boat, for as long as nobody answers it.
    """

    game = G.POOL_OF_RADIANCE

    def __init__(self, rows: list[str], answers: list[str] | None = None):
        self.kbd = FakeKeyboard()
        self.rows = list(rows)
        self.answers = list(answers or [])
        self.bars: list[str] = []
        self.walk_refused = None
        self.outdoor_boat = None
        self.messages: list[str] = []

    def screen(self):
        row = self.rows[0] if len(self.rows) == 1 else self.rows.pop(0)
        session = self

        class Screen:
            def row(self, r):
                return row if r == 24 else ""
        return Screen() if session is not None else None

    def select_bar(self, label, row=24, timeout=30.0):
        self.bars.append(label)
        if self.answers:
            self.rows = [self.answers.pop(0)]
        return True

    def handle_prompt(self, s=None):
        return False

    def log(self, *a):
        self.messages.append(" ".join(str(x) for x in a))


def test_the_boat_question_is_named_rather_than_pressed_at():
    """The defect: a digit went into `TAKE BOAT STAY` and nothing moved."""
    sess = BoatSession([WORLD_ROW, BOAT_ROW], answers=[BOAT_ROW])
    assert sess.outdoor_key("1", 0.0, 0.0, timeout=2.0) is False
    assert sess.kbd.sent == []
    assert "boat" in (sess.walk_refused or "")
    assert "not a wall" in (sess.walk_refused or "")


def test_a_run_that_says_which_way_it_wants_gets_past_the_boat():
    """`outdoor_boat` answers the question and the digit then reaches the
    prompt.  `STAY` is what a run measuring an overland step wants; `TAKE`
    would sail the party back to New Phlan."""
    sess = BoatSession([WORLD_ROW, BOAT_ROW], answers=[BOAT_ROW, PROMPT_ROW])
    sess.outdoor_boat = "STAY"
    assert sess.outdoor_key("1", 0.0, 0.0, timeout=5.0) is True
    assert sess.bars == ["MOVE", "STAY"]
    assert sess.kbd.sent == ["1"]


def test_an_ordinary_square_still_takes_move_and_then_the_digit():
    """The control.  Watched on `#190`'s engine-written outdoor save, four
    directions of four, one press each."""
    sess = BoatSession([WORLD_ROW], answers=[PROMPT_ROW])
    assert sess.outdoor_key("3", 0.0, 0.0, timeout=5.0) is True
    assert sess.bars == ["MOVE"]
    assert sess.kbd.sent == ["3"]
    assert sess.walk_refused is None


def test_a_prompt_already_up_needs_no_move_at_all():
    """A walked exit on to the grid lands with `1-8` already showing."""
    sess = BoatSession([PROMPT_ROW])
    assert sess.outdoor_key("7", 0.0, 0.0, timeout=5.0) is True
    assert sess.bars == []
    assert sess.kbd.sent == ["7"]


def test_answering_the_boat_does_not_spend_the_budget_for_the_prompt_behind_it():
    """The landing draws the boat off the disk, and that took most of twenty
    seconds on pool slot 1 -- so a run whose patience went on reaching the
    question had none left for the direction prompt and reported the step
    blocked anyway.  Answering the boat starts the wait again.

    A one-second budget makes it deterministic rather than timed: answering
    the bar sleeps a whole second by itself, so without the reset the deadline
    is already past by the time the prompt is looked for.
    """
    sess = BoatSession([WORLD_ROW, BOAT_ROW], answers=[BOAT_ROW, PROMPT_ROW])
    sess.outdoor_boat = "STAY"
    assert sess.outdoor_key("1", 0.0, 0.0, timeout=1.0) is True
    assert sess.kbd.sent == ["1"]


class DeafBoatSession(BoatSession):
    """A `select_bar` that answers nothing, which is the case with no end.

    Every reset of the deadline in `outdoor_key` comes after an answer, so a
    `select_bar` that presses nothing and reports it renews the wait on every
    look: the boat is still on row 24, the branch fires again, and the driver
    holds a pooled emulator slot until somebody notices.  Found by review of
    `d33c7b4`, 2026-09-07, before it ever ran overnight.
    """

    def select_bar(self, label, row=24, timeout=30.0):
        if label == "MOVE":
            return super().select_bar(label, row, timeout)
        self.bars.append(label)
        return False


def test_a_boat_answer_that_presses_nothing_stops_rather_than_waiting_for_ever():
    """`select_bar` reporting failure is the driver's own error, not a wall."""
    sess = DeafBoatSession([WORLD_ROW, BOAT_ROW], answers=[BOAT_ROW])
    sess.outdoor_boat = "STAY"
    assert sess.outdoor_key("1", 0.0, 0.0, timeout=1.0) is False
    assert sess.kbd.sent == []
    assert sess.bars == ["MOVE", "STAY"]
    assert "not a wall" in (sess.walk_refused or "")
    assert "STAY could not be found" in (sess.walk_refused or "")


def test_a_boat_that_will_not_go_away_is_answered_a_fixed_number_of_times():
    """`select_bar` says it pressed the answer and the question stays up, so
    nothing reports a failure and the deadline is renewed on every answer.
    `BOAT_ANSWERS` is what ends it."""
    sess = BoatSession([WORLD_ROW, BOAT_ROW], answers=[BOAT_ROW, BOAT_ROW,
                                                       BOAT_ROW, BOAT_ROW])
    sess.outdoor_boat = "TAKE"
    assert sess.outdoor_key("1", 0.0, 0.0, timeout=1.0) is False
    assert sess.bars == ["MOVE"] + ["TAKE"] * S.BOAT_ANSWERS
    assert sess.kbd.sent == []
    assert f"{S.BOAT_ANSWERS} times" in (sess.walk_refused or "")
    assert "not a wall" in (sess.walk_refused or "")


def test_an_unrecognised_row_24_is_a_driver_error_and_not_a_wall():
    """The third `False` this method can return, and the one that said
    nothing.  Row 24 is a bar nobody has named -- a disk prompt over the top
    of it, a screen glitch -- so no digit was sent and the step is not
    evidence of a wall.  A caller could not tell it from a party that walked
    into rock, which is the ambiguity `#360 (The session driver will not walk
    a Curse or Silver Blades party in a dungeon, because it reads Pool of
    Radiance's indoors flag)` was filed to remove.
    """
    sess = BoatSession(["SOMETHING NOBODY HAS SEEN" + " " * 15])
    assert sess.outdoor_key("4", 0.0, 0.0, timeout=1.0) is False
    assert sess.kbd.sent == []
    assert sess.bars == []
    assert "pressed nothing" in (sess.walk_refused or "")
    assert "not a wall" in (sess.walk_refused or "")
