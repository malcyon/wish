"""Driving a Pool of Radiance fight: what row 24 means, and the loop over it.

Nothing here needs an emulator or a display.  The screens are the ones the
harness actually saw -- every distinct row-24 bar in `work/p118-step3/*.log`,
404 readings across nine runs -- and the session is a fake that records the
keys it was asked to send.

807 row-24 readings across twelve logs hold 18 distinct bars, and this asserts
the kind of each.

The reason this is a test rather than a note is that the classifier is the only
thing standing between "the party won a fight" and "the party stood still until
the game offered to stop".  Both look identical in a log of command bars.
"""

import dataclasses
import pathlib
import sys

import pytest
from gamedata import synthetic_arena

# From this file, not from a path measured on somebody's machine: an absolute
# one exists here and nowhere else, and `tests/gamedata.py` carries the same
# lesson in its own docstring after two tests were invisible on CI that way.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

from session import (  # noqa: E402
    ATTACK,
    BAR_BLANK,
    BAR_COMMAND,
    BAR_CONTINUE,
    BAR_DONE,
    BAR_EXIT,
    BAR_MESSAGE,
    BAR_MOVE,
    BAR_NONE,
    BAR_PRESS,
    BAR_YESNO,
    COMBAT,
    DUNGEON,
    ENDED,
    LOST,
    LOST_TEXT,
    NOT_FIGHTING,
    PANEL_LEFT,
    RE_NOTABLE,
    STEP_KEYS,
    WON,
    Session,
    chebyshev,
    span_in,
    word_column,
)

from automap import combat  # noqa: E402
from automap.target import MemoryTarget  # noqa: E402

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


# -- what row 24 means ------------------------------------------------------

# Every distinct row-24 reading in `work/p118-step3/*.log`, with how many times
# it was seen -- 807 readings, 18 distinct.  The truncated ones and the row of
# screen border are bars caught mid-redraw, and they are why a half-drawn bar
# must not be forced into a kind.
MEASURED = [
    ("MOVE VIEW AIM USE QUICK DONE", 234, BAR_COMMAND),
    ("MOVE VIEW AIM USE CAST QUICK DONE", 59, BAR_COMMAND),
    ("MOVE VIEW AIM QUICK DONE", 18, BAR_COMMAND),
    # Not in those logs.  A character who has spent every square of movement
    # loses MOVE from its own command bar -- `work/p126/run1.log`, on the press
    # that took MOVE LEFT to 0.
    ("VIEW AIM USE QUICK DONE", 0, BAR_COMMAND),
    ("MOVE/ATTACK, MOVE LEFT = 9", 28, BAR_MOVE),
    ("MOVE/ATTACK, MOVE LEFT = 8", 13, BAR_MOVE),
    ("MOVE/ATTACK, MOVE LEFT = 12", 5, BAR_MOVE),
    ("MOVE/ATTACK, MOVE LEFT = 10", 4, BAR_MOVE),
    ("MOVE/ATTACK, MOVE LEFT = 6", 2, BAR_MOVE),
    ("MOVE/ATTACK, MOVE LEFT = 7", 1, BAR_MOVE),
    ("MOVE/ATTACK, MOVE LEFT = 5", 1, BAR_MOVE),
    ("MOVE/ATTACK, MOVE LEFT = 11", 1, BAR_MOVE),
    ("CONTINUE BATTLE : YES NO", 8, BAR_CONTINUE),
    # Not in those logs either.  This is what taking QUICK puts up --
    # `work/p126/quick.log` -- and `EXIT` backs out of it.
    # What DONE opens -- `work/p126/melee4.log`.  Not a treasure bar, though
    # it carries EXIT too: GUARD on it is what actually ends a turn.
    ("GUARD DELAY QUIT SPEED EXIT", 0, BAR_DONE),
    # GUARD is not always offered -- `work/p126/melee5.log`.  Same bar, and a
    # classifier that keyed on GUARD stopped recognising it.
    ("DELAY QUIT SPEED EXIT", 0, BAR_DONE),
    ("TAKE POOL SHARE DETECT VIEW EXIT", 0, BAR_EXIT),
    # What the game asks when a step would walk into a party member --
    # `work/p126/melee.log`.  It is the proof that a step onto an occupied
    # square is a blow.
    ("ATTACK ALLY: YES NO", 0, BAR_YESNO),
    ("GUARDING", 17, BAR_MESSAGE),
    ("YOUR TEAMMATE IS DYING", 11, BAR_MESSAGE),
    ("MOVE/AT", 1, BAR_MESSAGE),
    ("MO", 1, BAR_MESSAGE),
    ("%[[[[[[[[[[[[[[[[[[[[[%[[[[[[[[[[[[[[[[$", 1, BAR_MESSAGE),
    ("", 402, BAR_BLANK),
    # Not on a `fight:` line -- it is what row 24 says once the fight is over,
    # and it is where the six earlier runs left the party standing.
    ("PRESS <RETURN> OR BUTTON TO CONTINUE", 0, BAR_PRESS),
]


@pytest.mark.parametrize("bar,_count,kind", MEASURED)
def test_every_bar_the_harness_has_seen_is_classified(bar, _count, kind):
    sess = FakeSession([(COMBAT, bar_screen(bar))])
    assert sess.combat_state().kind == kind


def test_the_move_sub_bar_carries_its_own_count():
    sess = FakeSession([(COMBAT, bar_screen("MOVE/ATTACK, MOVE LEFT = 9"))])
    state = sess.combat_state()
    assert (state.kind, state.moves_left) == (BAR_MOVE, 9)


def test_no_screen_is_not_a_blank_bar():
    """A bitmap screen and an empty bar are different things.

    `screen()` returns None while the display is bitmap or the monitor is
    unreachable, and a driver that read that as "row 24 is empty" would sit
    waiting through a load it should have been answering prompts for.
    """
    sess = FakeSession([(COMBAT, None)])
    assert sess.combat_state().kind == BAR_NONE


# -- finding a command on the bar -------------------------------------------

def test_a_command_is_found_where_it_is_a_word_and_nowhere_else():
    """`word_column` is a guard, and it is worth saying what it is not.

    On every bar this project has measured, a plain `str.find` gives the same
    answer -- MOVE, VIEW, AIM, USE, CAST, QUICK, DONE, YES, NO and EXIT are
    none of them inside one another.  So this is protection against a command
    vocabulary we have not seen yet, not the fix for a bug we hit; `ON` inside
    `DONE` is what it stops, and there is no command called ON.
    """
    assert word_column("MOVE VIEW AIM USE QUICK DONE", "MOVE") == 0
    assert word_column("MOVE VIEW AIM USE QUICK DONE", "DONE") == 24
    assert word_column("MOVE VIEW AIM USE QUICK DONE", "ON") == -1
    # `QUICK` is on the command bar and `QUIT` is not, and `end_turn` asks for
    # QUIT at every bar `fight` calls it at.  A plain `find` gets this one
    # wrong the other way -- it answers -1 correctly here, but the guard is
    # what stops `QUIT` ever being read out of `QUICK`.
    assert word_column("MOVE VIEW AIM USE QUICK DONE", "QUIT") == -1
    assert word_column("MOVE/ATTACK, MOVE LEFT = 9", "DONE") == -1
    assert word_column("CONTINUE BATTLE : YES NO", "NO") == 22


def test_the_highlight_comes_from_the_snapshots_own_colours():
    s = command_bar("MOVE VIEW AIM USE QUICK DONE", "QUICK")
    assert span_in(s, 24) == (18, 22)


def test_a_blank_cell_is_never_the_start_of_the_highlight():
    """Colour RAM under a space keeps whatever the previous screen left there.

    Counting it would put the span's left edge in the gap before a command and
    send the walk one step the wrong way, every time.
    """
    s = bar_screen("MOVE VIEW", (24, 4, 8))     # the space at column 4 included
    assert span_in(s, 24) == (5, 8)             # the V of VIEW, not the gap


def test_the_walk_steps_right_then_presses_return():
    bar = "MOVE VIEW AIM USE QUICK DONE"
    frames = [(COMBAT, command_bar(bar, "MOVE")),
              (COMBAT, command_bar(bar, "VIEW")),
              (COMBAT, command_bar(bar, "DONE"))]
    sess = FakeSession(frames)
    assert sess.combat_bar("DONE", timeout=5) is True
    assert sess.kbd.sent == ["Right", "Right", "Return"]


def test_the_walk_will_not_act_on_the_move_sub_bar():
    """The trap that cost the draft in `work/p118-step3/run.py` its turns.

    `MOVE` is a word on `MOVE/ATTACK, MOVE LEFT = 9` as much as it is on the
    command bar, so no amount of care over matching saves this one.  What saves
    it is that the move sub-bar is not a menu at all: it is asking for a
    direction, and `Right` sent to it steps the character.
    """
    sess = FakeSession([(COMBAT, bar_screen("MOVE/ATTACK, MOVE LEFT = 9",
                                            (24, 0, 3)))])
    assert sess.combat_bar("MOVE", timeout=1.0) is False
    assert sess.kbd.sent == []


# -- the loop ---------------------------------------------------------------

STATUS = "S 10:56 14,5"


def test_a_fight_runs_to_the_world_and_says_the_party_won():
    """The whole sequence one driven fight goes through.

    The end of a fight is not the mode byte leaving 2: the win, the experience
    share and the `PRESS <RETURN>` all run afterwards, and a driver that stops
    at the mode byte leaves the party at a prompt for ever.
    """
    bar = "MOVE VIEW AIM USE QUICK DONE"
    frames = [
        (COMBAT, command_bar(bar, "DONE")),                 # a turn
        (COMBAT, bar_screen("")),                           # a monster's turn
        (COMBAT, command_bar("CONTINUE BATTLE : YES NO", "YES")),
        (COMBAT, command_bar("CONTINUE BATTLE : YES NO", "NO")),
        (DUNGEON, FakeScreen({6: "THE PARTY HAS WON !",
                              8: "EACH SHARE IS 25",
                              24: "PRESS <RETURN> OR BUTTON TO CONTINUE"})),
        (DUNGEON, FakeScreen({14: STATUS, 24: "MOVE VIEW CAST AREA ENCAMP"})),
    ]
    sess = FakeSession(frames)
    out = sess.fight(budget=20.0, poll=0.0)
    assert out.outcome == WON
    assert out.turns == 1
    assert "THE PARTY HAS WON !" in out.lines
    assert 0x0D in sess.injected          # the PRESS <RETURN> was answered
    assert out.bars[0] == bar
    assert "CONTINUE BATTLE : YES NO" in out.bars


def test_a_fight_the_party_loses_is_classified_from_the_screen():
    """The losing branch, exercised against the word `session.py` guesses.

    **`LOST_TEXT` is a guess and is said to be one** beside its definition:
    `THE PARTY HAS WON !` was read off two real fights and the losing wording
    off none, so `fight` reports `ended` rather than `lost` when it does not
    match.  This test does not claim the game says `DEFEATED`; it claims the
    classification works when the text it is looking for is on the screen, so
    the branch is not unexercised code that a later edit could break in
    silence.  `#128` is the ticket for reading the real wording off a fight
    the party actually loses.
    """
    bar = "MOVE VIEW AIM USE QUICK DONE"
    sess = FakeSession([
        (COMBAT, command_bar(bar, "DONE")),
        (DUNGEON, FakeScreen({6: f"THE PARTY IS {LOST_TEXT}",
                              24: "PRESS <RETURN> OR BUTTON TO CONTINUE"})),
        (DUNGEON, FakeScreen({14: STATUS, 24: "MOVE VIEW CAST AREA ENCAMP"})),
    ])
    out = sess.fight(budget=20.0, poll=0.0)
    assert out.outcome == LOST
    assert f"THE PARTY IS {LOST_TEXT}" in out.lines


def test_a_fight_that_never_ends_reports_its_budget_rather_than_a_win():
    bar = "MOVE VIEW AIM USE QUICK DONE"
    sess = FakeSession([(COMBAT, command_bar(bar, "DONE"))])
    out = sess.fight(budget=0.5, poll=0.0)
    assert out.outcome == "budget"
    assert out.acted is False


def test_the_party_standing_still_is_not_a_fight_it_fought():
    """`acted` is what tells a won fight from a fight nobody swung in.

    Six runs before this one ended with `THE PARTY HAS WON !` and no character
    having attacked, and the logs of command bars could not tell the two apart.
    """
    won = FakeSession([(COMBAT, bar_screen(""))])
    out = won.fight(budget=0.3, poll=0.0)
    assert out.acted is False
    assert out.blows == 0


# -- who swung ---------------------------------------------------------------

# The message band as `work/rolls/run2.jsonl` caught it, whole and unedited.
# The game prints into columns 23-38 (`COMBAT $0970`), one phrase to a row,
# and the **first row of a block is the name of whoever is speaking** --
# `$2994 JSR $34C3` prints the name at `$6B00` before the message text, which
# `automap/combatlog.py` documents.
#
# So the attacker's name is on the screen, two rows above the word that says
# what the blow did, and `HITS`/`MISSES`/`POINTS OF DAMAGE` are the same words
# whichever side swung.
ORCS_SWINGING = ["ORC", "ATTACKS", "BRUTUS", "AND MISSES..."]
PARTY_SWINGING = ["BRUTUS", "ATTACKS", "ORC", "AND HITS FOR 7",
                  "POINTS OF DAMAGE"]


def band(rows: list[str]) -> FakeScreen:
    """A combat screen whose message band carries `rows`, where the game puts
    them: down the right-hand window from row 10."""
    return FakeScreen({24: "",
                       **{10 + i: " " * 23 + t for i, t in enumerate(rows)}})


def test_a_fight_only_the_monsters_swung_in_is_not_one_the_party_fought():
    """The whole of `#163`, in the words the orcs actually printed.

    One Slums ambush drove 27 turns, passed 26 of them with the party standing
    next to the orcs, and reported `acted=True` -- off `AND MISSES...`, which
    was the orcs.  `RE_STRUCK` cannot tell an attacker from a defender, and the
    party is being attacked in every fight it is in, so the old `acted` was
    true of any fight that lasted a round.
    """
    sess = FakeSession([(COMBAT, band(ORCS_SWINGING))])
    out = sess.fight(budget=0.3, poll=0.0)
    assert "AND MISSES..." in out.lines      # the band was read, as before
    assert out.anybody_swung is True         # and somebody did swing
    assert out.acted is False                # but not a party member
    assert out.blows == 0


def test_acted_ignores_the_message_band_even_when_the_party_is_named():
    """The cost of not reading the band, stated rather than hidden.

    `BRUTUS ATTACKS ORC` really is a party member striking, and `acted` still
    answers False here because the driver did not strike -- it is the tactic's
    count, not a screen read.  That is deliberate and it is the safe direction:
    a check this one gets believed, and under-reporting costs a re-run where
    over-reporting costs a wrong conclusion about whether a converted party
    ever fought.

    It is also what makes name-matching unattractive.  The name is two rows
    above the verb, in a block that lives about a second of emulated time
    (`automap/combatlog.py`) while `fight` polls once a second -- and a
    character a player named `ORC` would read as an orc.
    """
    sess = FakeSession([(COMBAT, band(PARTY_SWINGING))])
    out = sess.fight(budget=0.3, poll=0.0)
    assert out.anybody_swung is True
    assert out.acted is False


def test_a_turn_that_ended_with_the_blow_struck_is_what_acted_counts():
    """A fight with nothing on the message band at all, and `acted` True.

    `melee_turn` answers `ATTACK` only when the step into an enemy's square
    was followed by the move sub-bar going away, which is the measured
    signature of a blow that resolved (`#127`).  `fight` counts those answers
    and that is the whole of `acted`.
    """
    bar = "MOVE VIEW AIM USE QUICK DONE"
    sess = FakeSession([(COMBAT, command_bar(bar, "DONE"))])
    out = sess.fight(budget=0.5, poll=0.0, tactic=lambda s, st: ATTACK)
    assert out.turns > 0
    assert out.blows == out.turns
    assert out.acted is True


def test_a_turn_the_tactic_passed_is_not_a_blow():
    """The same bar and the same budget as the test above, and the only
    difference is what the tactic did with the turn."""
    bar = "MOVE VIEW AIM USE QUICK DONE"
    sess = FakeSession([(COMBAT, command_bar(bar, "DONE"))])
    out = sess.fight(budget=0.5, poll=0.0, tactic=lambda s, st: "GUARD")
    assert out.turns > 0
    assert out.blows == 0
    assert out.acted is False


def test_a_result_says_what_acted_rests_on():
    """`#163` asks for the evidence beside the answer, and this is it.

    A run whose report says only `acted=True` is one somebody has to take on
    trust, and that is exactly how a fight nobody fought was believed.
    """
    sess = FakeSession([(COMBAT, band(ORCS_SWINGING))])
    out = sess.fight(budget=0.3, poll=0.0)
    assert out.evidence.startswith("A party member struck on 0 of ")
    assert "monsters attacking the party" in out.evidence

    bar = "MOVE VIEW AIM USE QUICK DONE"
    fought = FakeSession([(COMBAT, command_bar(bar, "DONE"))]).fight(
        budget=0.5, poll=0.0, tactic=lambda s, st: ATTACK)
    assert fought.evidence.startswith("A party member struck on "
                                      f"{fought.blows} of ")
    assert "monsters attacking" not in fought.evidence


# The two panel lines that made a fight nobody fought report a blow struck.
# Both are real captures, and both were the pattern being too loose rather than
# anything the game did.
PANEL_LIES = [
    "$                     $HIT POINTS 4    $",       # work/p126/quick.log
    "$THACO 17  DAMAGE 1D3                  $",       # work/p126/run1.log
]


@pytest.mark.parametrize("line", PANEL_LIES)
def test_a_panel_line_is_not_a_blow_struck(line):
    """The furniture is on the screen too, and it matches a loose pattern.

    `work/p126/quick.log` reported a blow landed in a fight whose 213 turns
    were all the driver bouncing off a sub-bar.  `acted` no longer reads the
    band at all, so this now guards `anybody_swung` and `lines` -- which are
    still what a run's log carries, and still what the next person to write a
    pattern over will reach for.
    """
    assert RE_NOTABLE.search(line.upper()) is None
    out = FakeSession([(COMBAT, bar_screen(""))]).fight(budget=0.3, poll=0.0)
    out.lines.append(line)
    assert out.anybody_swung is False


def test_a_real_blow_is_somebody_swinging_and_does_not_say_who():
    out = FakeSession([(COMBAT, bar_screen(""))]).fight(budget=0.3, poll=0.0)
    out.lines.append("PHINEAS MISSES")
    assert out.anybody_swung is True
    out.lines = ["THRENDER GRONE HITS FOR 6 POINTS OF DAMAGE"]
    assert out.anybody_swung is True
    assert out.acted is False           # neither line says which side swung


def test_fight_refuses_when_there_is_no_fight():
    sess = FakeSession([(DUNGEON, FakeScreen({14: STATUS}))])
    out = sess.fight(budget=5.0, poll=0.0)
    assert out.outcome == NOT_FIGHTING


def test_the_exit_bar_is_taken():
    frames = [
        (COMBAT, command_bar("TAKE  POOL  SHARE  DETECT  VIEW  EXIT", "TAKE")),
        (COMBAT, command_bar("TAKE  POOL  SHARE  DETECT  VIEW  EXIT", "EXIT")),
        (DUNGEON, FakeScreen({14: STATUS})),
    ]
    sess = FakeSession(frames)
    out = sess.fight(budget=10.0, poll=0.0)
    assert out.outcome == ENDED
    assert "Return" in sess.kbd.sent


# -- the melee turn ---------------------------------------------------------

def test_every_direction_has_a_key_and_standing_still_has_none():
    """The eight steps the numeric keypad makes, and no ninth.

    `melee_turn` looks the key up by the sign of the difference between two
    squares, so a missing entry is a character that silently does nothing on
    its turn.  `(0, 0)` has no key on purpose: the target is already under you,
    which cannot happen and would loop for ever if it did.
    """
    want = {(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - {(0, 0)}
    assert set(STEP_KEYS) == want
    assert (0, 0) not in STEP_KEYS
    assert all(k.startswith("KP_") for k in STEP_KEYS.values())
    assert len(set(STEP_KEYS.values())) == 8


class ArenaSession(FakeSession):
    """A `Session` over `tests/gamedata.py`'s arena: one fighter, one orc.

    The geometry is the real reader's -- `read_battle` over the position table
    and the parameter block -- so the direction `melee_turn` picks is chosen
    from squares rather than from anything this file made up.  What is faked is
    the screen: a command bar, then the move sub-bar counting its squares down,
    and `LAG` reads of the command bar in between because the game does not
    redraw row 24 the instant a key lands.
    """

    BAR = "MOVE VIEW AIM USE QUICK DONE"
    LAG = 2

    def __init__(self, battle, name, steps, highlight="MOVE"):
        self.battle_ = battle
        self.name = name
        self.left = steps
        col = word_column(self.BAR, highlight)
        self.command = FakeScreen({24: self.BAR, 2: " " * PANEL_LEFT + name},
                                  (24, col, col + len(highlight) - 1))
        super().__init__([(COMBAT, self.command)])
        self.moving_now = False
        self.lag = 0

    def battle(self):
        return self.battle_

    def screen(self):
        if not self.moving_now:
            return self.command
        if self.lag > 0:
            self.lag -= 1
            return self.command                # row 24 not redrawn yet
        return FakeScreen({24: f"MOVE/ATTACK, MOVE LEFT = {self.left}",
                           2: " " * PANEL_LEFT + self.name})

    def step(self):
        """A key was sent: Return takes MOVE, and a step spends a square."""
        if not self.moving_now:
            self.moving_now = True
            self.lag = self.LAG
        elif self.left > 0:
            self.left -= 1
            if self.left == 0:
                self.moving_now = False        # the turn ended


def test_melee_walks_the_acting_character_towards_the_nearest_enemy():
    """BRUTUS at (25,13), an orc at (30,13): the step is east, eight-way.

    This is the whole of what `#126` item 4 turned out to be -- there is no
    attack key, and a step into an occupied square is the blow.
    """
    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me, enemy = b.party[0], b.enemies[0]
    assert (me.x, me.y, enemy.x, enemy.y) == (25, 13, 30, 13)
    sess = ArenaSession(b, me.name, steps=3)
    assert sess.melee_turn(sess.combat_state()) == "MOVE"
    assert sess.kbd.sent == ["Return", "KP_6", "KP_6", "KP_6"]


def test_the_driver_waits_for_the_move_sub_bar_to_be_drawn():
    """The bar lags the keypress, and one read is not an answer.

    Reading row 24 straight after taking MOVE gives the command bar still.
    A driver that decides on that read backs out and takes MOVE again -- 638
    times in 420 seconds, with `MOVE LEFT = 12` never once going down, and not
    one blow struck (`work/p126/melee2.log`).
    """
    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me = b.party[0]
    sess = ArenaSession(b, me.name, steps=2)
    sess.LAG = 4                                # four stale reads, not two
    assert sess.melee_turn(sess.combat_state()) == "MOVE"
    assert sess.kbd.sent == ["Return", "KP_6", "KP_6"]


def test_the_acting_character_is_the_one_the_panel_names():
    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me = b.party[0]
    named = FakeScreen({2: " " * PANEL_LEFT + me.name})
    empty = FakeScreen({2: " " * PANEL_LEFT + "NOBODY"})
    sess = FakeSession([(COMBAT, named)])
    assert sess.acting(b, named) is not None
    assert sess.acting(b, named).index == me.index
    assert sess.acting(b, empty) is None
    assert sess.acting(None, named) is None


def test_a_turn_with_nothing_left_to_fight_passes_instead_of_moving():
    """Every enemy dead or gone: take DONE rather than walk into a corpse."""
    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me = b.party[0]
    dead = combat.Battle(shape=b.shape, terrain=b.terrain, camera=b.camera,
                         combatants=tuple(c for c in b.combatants
                                          if c.is_party))
    sess = ArenaSession(dead, me.name, steps=3, highlight="DONE")
    assert sess.melee_turn(sess.combat_state()) == "DONE"
    assert sess.kbd.sent == ["Return"]          # DONE, not MOVE


class _Party:
    """Just enough of a `Battle` for `acting`: it reads `battle.party` names."""

    def __init__(self, *names):
        self.party = tuple(
            type("Who", (), {"index": i, "name": n})() for i, n in enumerate(names))


def test_a_name_inside_another_name_does_not_steal_the_turn():
    """SEAN and BROTHER SEAN in one party, and the panel says BROTHER SEAN.

    Taking the first match in index order would hand every one of BROTHER
    SEAN's turns to SEAN, and the wrong character would walk into the orcs.
    The party this ran against carries BROTHER SEAN, so it is not a
    hypothetical shape.
    """
    party = _Party("SEAN", "BROTHER SEAN", "PHINEAS")
    sess = FakeSession([(COMBAT, FakeScreen({}))])
    panel = FakeScreen({2: " " * PANEL_LEFT + "BROTHER SEAN",
                        4: " " * PANEL_LEFT + "HIT POINTS 10"})
    assert sess.acting(party, panel).name == "BROTHER SEAN"
    assert sess.acting(party, FakeScreen({2: " " * PANEL_LEFT + "SEAN"})).name \
        == "SEAN"
    assert sess.acting(party, FakeScreen({2: " " * PANEL_LEFT + "NOBODY"})) is None


def test_a_yes_no_bar_nobody_recognises_is_answered_no():
    """`ATTACK ALLY: YES NO` had no branch at all and stalled a whole fight.

    421 seconds of a 421-second budget, one turn taken, and the log showed the
    bar sitting there being read over and over -- `work/p126/melee.log`.
    """
    frames = [
        (COMBAT, command_bar("ATTACK ALLY: YES NO", "YES")),
        (COMBAT, command_bar("ATTACK ALLY: YES NO", "NO")),
        (DUNGEON, FakeScreen({14: STATUS})),
    ]
    sess = FakeSession(frames)
    out = sess.fight(budget=10.0, poll=0.0)
    assert out.outcome == ENDED
    assert sess.kbd.sent == ["Right", "Return"]      # walked onto NO, took it


def test_the_step_towards_an_enemy_goes_round_an_ally_and_not_through_it():
    """A step onto an occupied square is a blow, ally or not.

    Walking PHINEAS at (26,11) straight west at DARKSTAR on (25,11) is what
    put `ATTACK ALLY: YES NO` on the screen.  The eight squares are ranked, and
    a party member's square is dropped -- an enemy's is not, because that step
    is the attack.
    """
    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me, enemy = b.party[0], b.enemies[0]              # (25,13) and (30,13)
    assert Session.step_towards(b, me, enemy) == "KP_6"

    ally = dataclasses.replace(me, index=1, x=me.x + 1, y=me.y)
    blocked = combat.Battle(shape=b.shape, terrain=b.terrain, camera=b.camera,
                            combatants=(me, ally) + b.enemies)
    key = Session.step_towards(blocked, me, enemy)
    assert key in ("KP_9", "KP_3")                    # round it, not through it

    # The enemy's own square is never dropped: that step is the blow.
    adjacent = dataclasses.replace(enemy, x=me.x + 1, y=me.y)
    touching = combat.Battle(shape=b.shape, terrain=b.terrain, camera=b.camera,
                             combatants=(me, adjacent))
    assert Session.step_towards(touching, me, adjacent) == "KP_6"


def test_a_step_that_gets_no_closer_is_not_taken():
    """Standing next to the target already: there is nothing left to walk."""
    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me = b.party[0]
    on_top = dataclasses.replace(b.enemies[0], x=me.x, y=me.y)
    same = combat.Battle(shape=b.shape, terrain=b.terrain, camera=b.camera,
                         combatants=(me, on_top))
    assert chebyshev(me, on_top) == 0
    assert Session.step_towards(same, me, on_top) is None


class WalledArena(ArenaSession):
    """An arena where the first direction tried costs nothing.

    `KP_4` did exactly this in the live sweep: the character pressed it, the
    square west was taken, and `MOVE LEFT` did not move (`work/p126/run1.log`).
    Nothing in the position table says why, so the driver has to notice that
    the count did not go down and try somewhere else.
    """

    WALLED = "KP_6"

    def step(self):
        if self.moving_now and self.kbd.sent[-1] == self.WALLED:
            return                              # the square is not there
        super().step()


def test_a_step_that_costs_nothing_is_not_tried_twice():
    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me = b.party[0]
    sess = WalledArena(b, me.name, steps=2)
    sess.melee_turn(sess.combat_state())
    steps = [k for k in sess.kbd.sent if k.startswith("KP_")]
    assert steps.count("KP_6") == 1             # tried once, then dropped
    assert len(steps) > 1                       # and something else was tried


def test_a_character_boxed_in_by_its_own_party_passes_its_turn():
    """The 638-turn stall, and the whole of why it never ended.

    PHINEAS at (26,11) had orcs two squares south and three party members on
    every square between.  `step_towards` was right to find nothing -- but
    taking MOVE and backing out does not end a turn, so the same command bar
    came back and the driver did it again for the whole 420-second budget with
    not one blow struck (`work/p126/melee3.log`).  A turn that cannot attack
    has to be passed.
    """
    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me, enemy = b.party[0], b.enemies[0]
    # Only the squares that get closer need blocking, which is exactly what
    # the party formation did to PHINEAS: three friends between him and the
    # orcs.  BRUTUS is at (25,13) and the orc at (30,13), so the three are
    # (26,12), (26,13) and (26,14).
    walls = [dataclasses.replace(me, index=i, x=me.x + 1, y=me.y + dy)
             for i, dy in enumerate((-1, 0, 1), start=1)]
    penned = combat.Battle(shape=b.shape, terrain=b.terrain, camera=b.camera,
                           combatants=(me,) + tuple(walls) + (enemy,))
    assert Session.step_towards(penned, me, enemy) is None

    sess = ArenaSession(penned, me.name, steps=3, highlight="DONE")
    assert sess.melee_turn(sess.combat_state()) == "DONE"
    assert sess.kbd.sent == ["Return"]           # DONE, and no MOVE at all


def test_passing_a_turn_takes_done_and_then_guard():
    """`DONE` does not end a turn; it opens a menu.

    Taking DONE and stopping leaves the same command bar up and the driver is
    asked again -- 210 turns in 420 seconds with no blow struck
    (`work/p126/melee4.log`).  `GUARD` on the sub-bar is what ends it, which is
    where the `GUARDING` on row 24 in the older logs was coming from.
    """
    bar = "MOVE VIEW AIM USE QUICK DONE"
    sub = "GUARD DELAY QUIT SPEED EXIT"
    frames = [
        (COMBAT, command_bar(bar, "DONE")),
        (COMBAT, command_bar(sub, "GUARD")),
        (COMBAT, bar_screen("GUARDING")),
    ]
    sess = FakeSession(frames)
    assert sess.combat_turn() == "GUARD"
    assert sess.kbd.sent == ["Return", "Return"]


def test_the_sub_bar_done_opens_is_not_a_treasure_bar():
    """Both carry EXIT, and taking EXIT out of the wrong one wastes the turn."""
    sess = FakeSession([(COMBAT, bar_screen("GUARD DELAY QUIT SPEED EXIT"))])
    assert sess.combat_state().kind == BAR_DONE
    sess = FakeSession([(COMBAT, bar_screen("TAKE POOL SHARE VIEW EXIT"))])
    assert sess.combat_state().kind == BAR_EXIT


def test_the_sub_bar_is_still_itself_without_guard_on_it():
    """`GUARD` drops off for a character that cannot take it.

    `DELAY QUIT SPEED EXIT` is the same bar, and a classifier keyed on GUARD
    stopped recognising it -- so `fight` read it as a treasure bar, took EXIT,
    and got the same command bar back (`work/p126/melee5.log`).
    """
    sess = FakeSession([(COMBAT, bar_screen("DELAY QUIT SPEED EXIT"))])
    assert sess.combat_state().kind == BAR_DONE


SUB_NO_GUARD = "DELAY QUIT SPEED EXIT"


def test_a_turn_with_no_guard_offered_is_quit_rather_than_delayed():
    """`DELAY` postpones a character; it does not finish with it.

    That is the whole of `#165`.  The driver took DELAY at this bar, the same
    character came straight back to the front of the queue, and one character
    who could not strike took **50 of the 54 turns** of a fight while the
    other five never acted again (`work/issue127/after1.jsonl`).

    `QUIT` is on this bar and on the one with GUARD, and it ends the turn --
    Donald, who plays this game, on 2026-09-01: *"In Combat, QUIT ends the
    turn immediately."*  This test replaces one that asserted DELAY here,
    which pinned the behaviour that starved the fight.
    """
    frames = [
        (COMBAT, command_bar(SUB_NO_GUARD, "DELAY")),
        (COMBAT, command_bar(SUB_NO_GUARD, "QUIT")),
    ]
    sess = FakeSession(frames)
    assert sess.end_turn() == "QUIT"
    assert sess.kbd.sent == ["Right", "Return"]


def test_guard_is_still_preferred_when_the_bar_offers_it():
    """Both end the turn, and GUARD leaves the character guarding as well."""
    sess = FakeSession([(COMBAT, command_bar("GUARD DELAY QUIT SPEED EXIT",
                                             "GUARD"))])
    assert sess.end_turn() == "GUARD"


class TurnQueue(FakeSession):
    """Two characters, and a sub-bar that does what the game's does.

    `GUARD` is offered to the second and not to the first -- the shape
    MALCYON's bar had all through the fight in `#165`.  Taking `DELAY` hands
    the turn back to **the same** character; `GUARD` and `QUIT` move on to the
    next.  That is the only difference between a fight that goes round the
    party and one that asks one character 50 times.
    """

    ORDER = ("MALCYON", "MAGNUS")
    BAR = "MOVE VIEW AIM USE QUICK DONE"

    def __init__(self):
        super().__init__([(COMBAT, None)])
        self.who = 0
        self.bar = self.BAR
        self.cursor = 0
        self.asked: list[str] = []          # who was asked for a command

    def sub_bar(self) -> str:
        return SUB_NO_GUARD if self.who == 0 else "GUARD " + SUB_NO_GUARD

    def words(self) -> list[str]:
        return self.bar.split()

    def screen(self):
        word = self.words()[self.cursor]
        col = word_column(self.bar, word)
        return FakeScreen({24: self.bar,
                           2: " " * PANEL_LEFT + self.ORDER[self.who]},
                          (24, col, col + len(word) - 1))

    def mode(self):
        return COMBAT

    def step(self):
        key = self.kbd.sent[-1]
        if key == "Right":
            self.cursor = min(self.cursor + 1, len(self.words()) - 1)
        elif key == "Left":
            self.cursor = max(self.cursor - 1, 0)
        elif key == "Return":
            self.take(self.words()[self.cursor])

    def take(self, word: str) -> None:
        if word == "DONE":
            self.bar = self.sub_bar()
        else:
            if word in ("GUARD", "QUIT"):
                self.who = (self.who + 1) % len(self.ORDER)
            self.bar = self.BAR             # DELAY and EXIT: the same one again
        self.cursor = 0

    def combat_turn(self):
        self.asked.append(self.ORDER[self.who])
        return super().combat_turn()


def test_a_character_that_cannot_guard_does_not_take_every_turn():
    """The outcome `#165` is about, rather than the command that produces it.

    One character whose sub-bar carries no GUARD, and four turns driven.  With
    `DELAY` taken there the answer is MALCYON four times and MAGNUS never --
    which is what a fight of 56 driven turns looked like, 50 of them one
    character's.
    """
    sess = TurnQueue()
    for _ in range(4):
        sess.combat_turn()
    assert sess.asked == ["MALCYON", "MAGNUS", "MALCYON", "MAGNUS"]


class RecordingBars(FakeSession):
    """A `FakeSession` that remembers which labels it was asked for."""

    def __init__(self, frames):
        super().__init__(frames)
        self.asked: list[str] = []

    def combat_bar(self, label, timeout=20.0, row=24):
        self.asked.append(label)
        return super().combat_bar(label, timeout, row)


def test_end_turn_asks_only_for_a_command_that_is_on_the_bar():
    """`combat_bar` cannot say "not here"; it waits out its whole timeout.

    Asking for GUARD, DELAY and EXIT blind spent 441 of one 605-second
    fight's seconds -- 73% of it -- waiting for words that were not on row
    24 (`#127`, `work/issue127/diag1.jsonl`).  Reading the bar first costs one
    screen read.
    """
    sess = RecordingBars([(COMBAT, command_bar(SUB_NO_GUARD, "DELAY")),
                          (COMBAT, command_bar(SUB_NO_GUARD, "QUIT"))])
    assert sess.end_turn() == "QUIT"
    assert sess.asked == ["QUIT"]               # never GUARD, which is not there


def test_end_turn_at_a_bar_with_no_way_out_asks_for_nothing():
    """`fight` calls `end_turn` whenever row 24 reads as the sub-bar, and a
    bar caught mid-redraw is not one.  Three blind tries there cost 24
    seconds; reading first costs nothing and the turn is retried next poll."""
    sess = RecordingBars([(COMBAT, command_bar("MOVE VIEW AIM USE QUICK DONE",
                                               "MOVE"))])
    assert sess.end_turn() == ""
    assert sess.asked == []


class AttackArena(ArenaSession):
    """An arena where the orc is next door and the blow lands.

    What the game actually does, measured at a live sub-bar: `MOVE LEFT` does
    not go down, nobody moves, the target loses hit points and the move
    sub-bar goes away a moment later -- ROLAND at (29,13) against an orc on
    (28,14), 9 squares before and 9 after, the orc 5 hit points before and 1
    after (`work/issue127/sweep1.jsonl`, turn 15).
    """

    def __init__(self, battle, name, steps, resolve=2, highlight="MOVE"):
        super().__init__(battle, name, steps, highlight)
        self.resolve = resolve
        self.struck = False

    def step(self):
        if not self.moving_now:
            self.moving_now = True
            self.lag = self.LAG
        else:
            self.struck = True              # the blow spends no square

    def screen(self):
        if self.struck and self.moving_now:
            self.resolve -= 1
            if self.resolve <= 0:
                self.moving_now = False
        return super().screen()


def test_a_step_onto_an_enemy_is_a_blow_and_is_never_avoided():
    """The whole of `#127`.

    An attack costs no movement, so "the count did not go down, therefore the
    step did not happen" puts the one key that would land the blow into
    `avoid` -- and the character then passes its turn standing next to the
    orc.  26 of 27 turns of one fight went that way.
    """
    b = combat.read_battle(MemoryTarget(synthetic_arena(
        fighters=((0, 25, 13), (8, 26, 13)))))
    me = b.party[0]
    assert chebyshev(me, b.enemies[0]) == 1
    sess = AttackArena(b, me.name, steps=9, resolve=3)
    assert sess.melee_turn(sess.combat_state()) == "ATTACK"
    assert sess.kbd.sent == ["Return", "KP_6"]      # MOVE, then the blow


class RefusedArena(ArenaSession):
    """A blow the game will not let this character strike.

    MALCYON with `13 DART` readied: six presses into the orc on the next
    square, each watched for ten seconds with nothing else sent, and the
    sub-bar never went away, no message and no damage
    (`work/issue127/probe1.jsonl`).
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.left_move = False

    def step(self):
        if not self.moving_now and not self.left_move:
            self.moving_now = True
            self.lag = self.LAG
        # and the attack key does nothing at all

    def press_kernal(self, code):
        """Backing out of move mode, and the bar comes back on `DONE`."""
        self.injected.append(code)
        self.moving_now = False
        self.left_move = True
        col = word_column(self.BAR, "DONE")
        self.command = FakeScreen(
            {24: self.BAR, 2: " " * PANEL_LEFT + self.name},
            (24, col, col + len("DONE") - 1))


def test_a_blow_the_game_refuses_passes_the_turn_rather_than_pressing_on():
    b = combat.read_battle(MemoryTarget(synthetic_arena(
        fighters=((0, 25, 13), (8, 26, 13)))))
    me = b.party[0]
    sess = RefusedArena(b, me.name, steps=9)
    sess.ATTACK_TIMEOUT = 0.5
    assert sess.melee_turn(sess.combat_state()) == "DONE"
    assert sess.kbd.sent.count("KP_6") == 1         # pressed once, not eight
    assert sess.injected == [0x0D]                  # and move mode left


class LaggingCount(ArenaSession):
    """Row 24's count lags the keypress by two reads."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pending = 0

    def step(self):
        if not self.moving_now:
            self.moving_now = True
            self.lag = self.LAG
        elif self.left > 0:
            self.pending = 2                # it happened; the screen is behind

    def screen(self):
        if self.moving_now and self.pending:
            self.pending -= 1
            if self.pending == 0:
                self.left -= 1
                if self.left == 0:
                    self.moving_now = False
        return super().screen()


def test_a_step_whose_count_lags_is_not_taken_for_one_that_failed():
    """One read 20 ms after the key says the game has not caught up yet.

    `melee_turn` used to read the count straight back and drop the direction
    when it had not moved -- and the read came back in 0.02 s on all 27 turns
    of the fight in `#127`, because it was asking for the bar it was already
    looking at.
    """
    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me = b.party[0]
    sess = LaggingCount(b, me.name, steps=2)
    assert sess.melee_turn(sess.combat_state()) == "MOVE"
    assert sess.kbd.sent == ["Return", "KP_6", "KP_6"]
