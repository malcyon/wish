"""The C64 `join` step: the walk onto a join square and the Curse Pit's script
screens answered by their text, one guarded key each, on fake screens."""

from __future__ import annotations

import pytest

from automap.screen import Screen
from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS as CURSE
from tools.c64 import acceptance as A
from tools.c64 import joinstep as J

PIT = J.site_for(CURSE.key, 0x11)
CONTINUE = "PRESS BUTTON OR RETURN TO CONTINUE."
WORLD = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"


def code(ch: str) -> int:
    if "A" <= ch <= "Z":
        return ord(ch) - ord("A") + 1
    return ord(ch)


def screen(rows: dict[int, str], lit: tuple[int, int, int] | None = None,
           panel: tuple[str, ...] = ()) -> Screen:
    """A screen with ROWS' text, the cells of LIT (row, first, last column)
    in white and the rest light blue, and PANEL's names in the world panel."""
    codes = bytearray([0x20] * 1000)
    colours = bytearray([14] * 1000)
    rows = dict(rows)
    for i, name in enumerate(panel):
        rows[3 + i] = " " * A.S.PARTY_COLUMN + name
    for r, text in rows.items():
        for c, ch in enumerate(text[:40]):
            codes[r * 40 + c] = code(ch)
    if lit is not None:
        r, first, last = lit
        for c in range(first, last + 1):
            colours[r * 40 + c] = 1
    return Screen(bytes(codes), bytes(colours), 0x0400)


def bar(words: str, lit: str) -> Screen:
    """Row 24 reading WORDS with the word LIT highlighted."""
    col = J.word_at(words, lit)
    return screen({24: words}, (24, col, col + len(lit) - 1))


class Game:
    """Screens in order; each key moves to the screen the table names for it,
    and a key the table does not name changes nothing."""

    def __init__(self, script: list, clock_step: float = 0.3):
        self.at = 0
        self.script = script
        self.keys: list[int] = []
        self.now = 0.0
        self.clock_step = clock_step

    def screen(self):
        return self.script[self.at][0]

    def press(self, key: int) -> None:
        self.keys.append(key)
        moves = self.script[self.at][1]
        if key in moves:
            self.at = moves[key]

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        # A screen with a timed move (key None) gives way on its own.
        moves = self.script[self.at][1]
        if None in moves:
            self.at = moves[None]

    def answerer(self) -> J.JoinAnswerer:
        return J.JoinAnswerer(self.screen, self.press, clock=self.clock,
                              sleep=self.sleep)


R, RT, LT = J.RETURN, J.RIGHT, J.LEFT


def pit_script(after_yes: Screen | None = None) -> list:
    """The Pit join as ECL11 `$89DC`-`$8D89` draws it."""
    first = "COMBAT ADVANCE WAIT FLEE PARLAY"
    parlay = "PARLAY:HAUGHTY SLY NICE MEEK ABUSIVE"
    listing = screen({17: "WHAT DO YOU DO?", 18: "TELL HER YOUR STORY",
                      19: "TELL HER YOU'RE HUNTING CULTISTS",
                      20: "TELL HER IT'S NONE OF HER AFFAIR"}, (18, 0, 18))
    world = screen({24: WORLD}, (24, 0, 3), panel=("WISHFTR", "ALIAS",
                                                  "DRAGONBAIT"))
    s = [
        (screen({17: "YOU SEE A FEMALE FIGHTER"}), {None: 1}),     # 0 text
        (screen({24: CONTINUE}), {R: 2}),                          # 1
        (bar(first, "COMBAT"), {RT: 3}),                           # 2
        (bar(first, "ADVANCE"), {RT: 4, LT: 2}),                   # 3
        (bar(first, "WAIT"), {RT: 5, LT: 3}),                      # 4
        (bar(first, "FLEE"), {RT: 6, LT: 4}),                      # 5
        (bar(first, "PARLAY"), {R: 7, LT: 5}),                     # 6
        (screen({24: "PICK SPEAKER"}, (5, 17, 23)), {R: 8}),       # 7
        (bar(parlay, "HAUGHTY"), {RT: 9}),                         # 8
        (bar(parlay, "SLY"), {RT: 10, LT: 8}),                     # 9
        (bar(parlay, "NICE"), {R: 11, LT: 9}),                     # 10
        (screen({24: CONTINUE}), {R: 12}),                         # 11
        (listing, {R: 13}),                                        # 12
        (screen({24: CONTINUE}), {R: 14}),                         # 13
        (bar("NO YES", "NO"), {RT: 15}),                           # 14
        (bar("NO YES", "YES"), {R: 16 if after_yes is None else 17}),  # 15
        (screen({24: CONTINUE}), {R: 18}),                         # 16
        (after_yes or screen({}), {}),                             # 17
        (world, {}),                                               # 18
    ]
    return s


PIT_KEYS = [R, RT, RT, RT, RT, R, R, RT, RT, R, R, R, R, RT, R, R]


def test_the_pit_join_is_answered_in_the_scripts_order_and_ends_on_the_world_bar():
    game = Game(pit_script())
    got = game.answerer().run(PIT)
    assert game.keys == PIT_KEYS
    assert [s["screen"] for s in got["screens"] if s["screen"] != "continue"] == [
        "the bar COMBAT ADVANCE WAIT FLEE PARLAY", "PICK SPEAKER",
        "the bar HAUGHTY SLY NICE MEEK ABUSIVE", "the list WHAT DO YOU DO?",
        "the bar NO YES"]
    assert got["joins"] == ["ALIAS", "DRAGONBAIT"] and got["area"] == 0x11


def test_the_pit_site_is_read_from_ecl11_and_answers_only_the_join_path():
    assert PIT.script == "ECL11"
    first, speaker, parlay, listing, yes = PIT.screens
    # PARLAY is index 4 of the opening menu, the arm to $8B6B; ABUSIVE is
    # the only PARLAY answer whose operand sends the party away.
    assert first.answer == "PARLAY" and first.words.index("PARLAY") == 4
    assert parlay.answer != "ABUSIVE" and parlay.answer in parlay.words
    assert isinstance(speaker, J.Speaker) and isinstance(listing, J.Listing)
    assert yes.words == ("NO", "YES") and yes.answer == "YES"


@pytest.mark.parametrize("other", [
    "COMBAT WAIT FLEE ADVANCE",             # the encounter menu, not the script's
    "COMBAT ADVANCE WAIT FLEE",             # a word short
    "YES NO",                               # a question nobody expects here
])
def test_an_unexpected_bar_stops_the_step_with_nothing_pressed(other):
    game = Game([(bar(other, other.split()[0]),
                  {R: 0, RT: 0, LT: 0})])
    with pytest.raises(J.JoinStopped, match="does not expect"):
        game.answerer().run(PIT)
    assert game.keys == []


def test_an_unexpected_bar_after_some_answers_gets_no_key():
    script = pit_script()
    script[7] = (bar("HAUGHTY SLY NICE MEEK ABUSIVE", "HAUGHTY"), {R: 8})
    game = Game(script)
    with pytest.raises(J.JoinStopped):
        game.answerer().run(PIT)
    # Everything up to PARLAY was answered; the screen that is not the
    # speaker pick got nothing.
    assert game.keys == PIT_KEYS[:6] and game.at == 7


def test_the_world_bar_before_the_last_answer_stops_the_step():
    script = pit_script()
    script[15] = (bar("NO YES", "YES"), {R: 18})
    script[13] = (screen({24: CONTINUE}), {R: 18})
    game = Game(script)
    with pytest.raises(J.JoinStopped, match="world bar came back before "
                                            "the bar NO YES"):
        game.answerer().run(PIT)


def test_a_key_that_changes_nothing_is_never_pressed_again():
    script = pit_script()
    script[6] = (bar("COMBAT ADVANCE WAIT FLEE PARLAY", "PARLAY"), {LT: 5})
    game = Game(script)
    with pytest.raises(J.JoinStopped, match="did not change"):
        game.answerer().run(PIT)
    assert game.keys == PIT_KEYS[:6] and game.keys.count(R) == 2


def test_a_save_disk_prompt_stops_the_step_unanswered():
    prompt = screen({18: "INSERT YOUR SAVE GAME DISK",
                     24: "PRESS ANY KEY TO CONTINUE"})
    game = Game([(prompt, {R: 0})])
    answered = []
    with pytest.raises(J.JoinStopped, match="disk prompt"):
        J.JoinAnswerer(game.screen, game.press, clock=game.clock,
                       sleep=game.sleep,
                       prompt=lambda s: answered.append(s) or True).run(PIT)
    assert game.keys == [] and answered == []


def test_the_sites_are_the_curse_pit_and_the_silver_blades_compound():
    assert J.site_for(CURSE.key, 0x11) is PIT and not PIT.arrival
    assert J.site_for(CURSE.key, 0x01) is None
    assert J.site_for("secret-of-the-silver-blades", 0x04) is None
    assert [(s.title, s.area) for s in J.JOIN_SITES] == [
        (CURSE.key, 0x11), ("secret-of-the-silver-blades", 0x44)]


# --- the step in the acceptance driver ------------------------------------------

def test_join_parses_dungeon_moves_ending_on_a_step():
    steps = A.parse_steps(["load", "join IIIKIIKIJIIKI", "save"])
    assert steps[1] == A.Step("join", "IIIKIIKIJIIKI")
    for bad in ("join IIK", "join IIM", "join 22", "join"):
        with pytest.raises(ValueError):
            A.parse_steps(["load", bad])


@pytest.mark.parametrize("title", ["pool", "ssb"])
def test_join_is_curse_only(tmp_path, capsys, title):
    with pytest.raises(SystemExit):
        A.main(["--title", title, "--save", str(tmp_path / "x.d64"),
                "--steps", "load", "join I", "--out", str(tmp_path)])
    assert "the join step: Curse of the Azure Bonds only" in capsys.readouterr().err


class FakeSession:
    """A party at 1,3 facing south that a walk leaves there, whose last move
    puts it on 1,4.  The world bar stays up for WORLD_READS reads after that
    move, as it does while the script loads its picture, before the Pit's
    screens come up."""

    def __init__(self, game: Game, area: int = 0x11, world_reads: int = 5):
        self.game = game
        self.area = area
        self.square = [1, 3, 2]
        self.moves: list[str] = []
        self.no_encounters = False
        self.held_at_move: list[bool] = []
        self.moved = False
        self.world_reads = world_reads

    def screen(self):
        if not self.moved:
            return screen({24: WORLD}, (24, 0, 3), panel=("WISHFTR",))
        if self.world_reads > 0:
            self.world_reads -= 1
            return screen({24: WORLD}, (24, 0, 3), panel=("WISHFTR",))
        return self.game.screen()

    def press_kernal(self, key):
        self.game.press(key)

    def walk_one(self, move, tries=1, answer_prompts=True):
        self.moves.append(move)
        self.held_at_move.append(self.no_encounters)
        self.square = [1, 4, 2]
        self.moved = True
        return True

    def stable_party_rows(self):
        return [3, 4, 5]

    def handle_prompt(self, s=None):
        return False


def _run(monkeypatch, sess, walked):
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess, run.game = sess, CURSE
    run.no_encounters = False
    run.gate_reports = None
    run.to_world = lambda tries=10: True
    run.leave_arrival = lambda step, presses=0: None
    run.capture = lambda tag, rows=None: []
    run.walk = lambda route: walked.append(route) or {"route": route}
    run.position = lambda: list(sess.square)
    run.steady_position = lambda: list(sess.square)
    run.log = type("L", (), {"say": staticmethod(lambda text: None),
                             "emit": staticmethod(lambda *a, **k: None)})()
    run.fail = lambda tag, why: A.StepFailed(why)
    monkeypatch.setattr(A.auto_actions.FastTravel, "current_area",
                        staticmethod(lambda target, addresses=None: sess.area))
    monkeypatch.setattr(A, "SessTarget", lambda s: s)
    real = J.JoinAnswerer

    def answerer(screen, press, **kw):
        kw.update(clock=sess.game.clock, sleep=sess.game.sleep)
        return real(screen, press, **kw)

    monkeypatch.setattr(A.joinstep, "JoinAnswerer", answerer)
    return run


def test_the_join_step_walks_all_but_the_last_move_then_answers_the_square(
        monkeypatch):
    game = Game(pit_script())
    sess = FakeSession(game)
    walked: list[str] = []
    run = _run(monkeypatch, sess, walked)
    got = run.join("iiikiikijiiki")
    assert walked == ["IIIKIIKIJIIK"] and sess.moves == ["I"]
    assert game.keys == PIT_KEYS
    assert got["square"] == [1, 4, 2] and got["route"] == "IIIKIIKIJIIKI"
    assert any("DRAGONBAIT" in row for row in got["panel"])


def test_the_join_step_holds_the_gates_for_the_last_move_when_asked(monkeypatch):
    game = Game(pit_script())
    sess = FakeSession(game)
    run = _run(monkeypatch, sess, [])
    run.no_encounters = True
    restored = []
    run.restore_gates = lambda when: restored.append(when) or {"when": when}
    got = run.join("I")
    assert sess.held_at_move == [True] and sess.no_encounters is False
    assert restored == ["join I"] and got["encounter_gates"] == {"when": "join I"}


def test_the_join_step_in_an_area_with_no_site_presses_nothing(monkeypatch):
    game = Game(pit_script())
    sess = FakeSession(game, area=0x01)
    walked: list[str] = []
    run = _run(monkeypatch, sess, walked)
    with pytest.raises(A.StepFailed, match="no join site in area 1"):
        run.join("II")
    assert walked == [] and sess.moves == [] and game.keys == []


def test_the_join_step_stops_when_the_last_move_is_blocked(monkeypatch):
    game = Game(pit_script())
    sess = FakeSession(game)
    sess.walk_one = lambda move, tries=1, answer_prompts=True: False
    run = _run(monkeypatch, sess, [])
    with pytest.raises(A.StepFailed, match="last move"):
        run.join("I")
    assert game.keys == []


# --- bounded waits, highlight and text checks before a key, gates put back ------

class Looped(RuntimeError):
    """A fake clock ran past any bound the step has: the step never stops."""


def test_an_unreadable_screen_stops_the_step_within_its_wait():
    game = Game([(screen({}), {})])
    game.screen = lambda: None
    sleep = game.sleep

    def bounded(seconds):
        sleep(seconds)
        if game.now > 10 * J.SCREEN_SECONDS:
            raise Looped(game.now)

    game.sleep = bounded
    with pytest.raises(J.JoinStopped, match="could not be read"):
        game.answerer().run(PIT)
    assert game.keys == []


def test_the_world_bar_lasting_past_the_grace_stops_with_nothing_pressed(
        monkeypatch):
    game = Game(pit_script())
    sess = FakeSession(game, world_reads=10 ** 6)
    run = _run(monkeypatch, sess, [])
    with pytest.raises(A.StepFailed, match="world bar stood unchanged"):
        run.join("I")
    assert game.keys == [] and game.now >= J.FIRST_SCREEN_GRACE


def test_the_list_gets_no_return_while_its_highlight_is_off_the_first_line():
    script = pit_script()
    listing, moves = script[12]
    off = screen({r: listing.row(r) for r in range(17, 21)}, (19, 0, 31))
    script[12] = (off, moves)
    game = Game(script)
    with pytest.raises(J.JoinStopped, match="first line"):
        game.answerer().run(PIT)
    assert game.keys == PIT_KEYS[:11] and game.at == 12


def test_a_continue_bar_the_script_does_not_draw_gets_no_return():
    script = pit_script()
    script[1] = (screen({24: "PRESS ANY KEY TO CONTINUE"}), {R: 2})
    game = Game(script)
    with pytest.raises(J.JoinStopped):
        game.answerer().run(PIT)
    assert game.keys == []


def test_each_continue_answered_logs_the_text_above_it():
    script = pit_script()
    script[1] = (screen({17: "YOU SEE A FEMALE FIGHTER", 24: CONTINUE}), {R: 2})
    game = Game(script)
    got = game.answerer().run(PIT)
    first = [s for s in got["screens"] if s["screen"] == "continue"][0]
    assert first["text"][0] == "YOU SEE A FEMALE FIGHTER"


def test_the_speaker_pick_is_matched_only_on_a_row_of_its_own():
    script = pit_script()
    script[7] = (screen({18: "YOU PICK SPEAKERS WITH CARE"}), {R: 8})
    game = Game(script)
    with pytest.raises(J.JoinStopped):
        game.answerer().run(PIT)
    assert game.keys == PIT_KEYS[:6] and game.at == 7


def test_a_stopped_join_puts_the_encounter_gates_back(monkeypatch):
    script = pit_script()
    script[2] = (bar("YES NO", "YES"), {R: 2})
    game = Game(script)
    sess = FakeSession(game)
    run = _run(monkeypatch, sess, [])
    run.no_encounters = True
    restored = []
    run.restore_gates = lambda when: restored.append(when) or {"when": when}
    with pytest.raises(A.StepFailed):
        run.join("I")
    assert restored == ["join I"] and sess.no_encounters is False


# --- the Pit square's text printing under the walk's move sub-bar ---------------

MOVE = "I,J,K,M, RETURN OR BUTTON"
#: What `ECL11 $89EF`-`$8A44` prints before its first continue bar, in the
#: rows the Pit run's frames show it (`07-lost-join`).
PIT_TEXT = ("YOU SEE A FEMALE FIGHTER AND A", "STRANGE-LOOKING LIZARD MAN.",
            "THE SHARP SCENTS OF VIOLETS, BRIMSTONE",
            "AND HONEYSUCKLE FOLLOW RAPIDLY UPON EACH",
            "OTHER.")


def printing(per_poll: int = 2, bottom: str = MOVE) -> list:
    """The square's text appearing PER_POLL characters a poll under BOTTOM,
    each frame giving way to the next on its own."""
    frames, shown = [], 0
    total = sum(len(line) for line in PIT_TEXT)
    while shown <= total:
        rows, left = {24: bottom}, shown
        for r, line in enumerate(PIT_TEXT):
            rows[17 + r] = line[:max(left, 0)]
            left -= len(line)
        frames.append((screen(rows), {None: len(frames) + 1}))
        shown += per_poll
    return frames


def pit_after_printing(per_poll: int = 2, end: Screen | None = None) -> list:
    """`printing`, then the Pit's screens from the first continue bar, ending
    on END in place of the world bar."""
    head = printing(per_poll)
    rest = pit_script()[1:]
    if end is not None:
        rest[-1] = (end, {})
    shift = len(head) - 1
    rest = [(s, {k: v + shift for k, v in moves.items()}) for s, moves in rest]
    return head + rest


def test_the_pit_text_printing_under_the_move_bar_gets_no_key_and_the_join_goes_on():
    # The Pit run stopped here: row 24 still the move sub-bar from the walk,
    # the square's text half printed, after UNEXPECTED_SECONDS.
    game = Game(pit_after_printing())
    got = game.answerer().run(PIT)
    printed = len(printing())
    assert game.now > J.UNEXPECTED_SECONDS and printed * J.POLL > 20
    assert game.keys == PIT_KEYS
    assert got["keys"][0] == {"key": "$0D", "row24": CONTINUE}


def test_the_join_ends_on_the_move_bar_the_script_comes_back_to():
    game = Game(pit_after_printing(end=screen({24: MOVE})))
    got = game.answerer().run(PIT)
    assert game.keys == PIT_KEYS and len(got["screens"]) > 5


def test_a_move_bar_left_standing_unchanged_stops_within_the_grace():
    game = Game([(screen({24: MOVE}), {R: 0})])
    with pytest.raises(J.JoinStopped, match="move bar stood unchanged"):
        game.answerer().run(PIT)
    assert game.keys == []
    assert J.FIRST_SCREEN_GRACE <= game.now < J.FIRST_SCREEN_GRACE + 1


def test_a_move_bar_over_text_that_never_ends_stops_within_the_screen_wait():
    frames = [(screen({17: "X" * (i % 40 + 1), 24: MOVE}), {None: i + 1})
              for i in range(1000)]
    game = Game(frames)
    with pytest.raises(J.JoinStopped, match="never came up"):
        game.answerer().run(PIT)
    assert game.keys == [] and game.now <= J.SCREEN_SECONDS + 1


def test_the_move_bar_after_a_key_stops_the_step():
    script = pit_script()
    script[6] = (bar("COMBAT ADVANCE WAIT FLEE PARLAY", "PARLAY"),
                 {R: 19, LT: 5})
    script.append((screen({24: MOVE}), {R: 19}))
    game = Game(script)
    with pytest.raises(J.JoinStopped, match="move bar came back before "
                                            "PICK SPEAKER"):
        game.answerer().run(PIT)
    assert game.keys == PIT_KEYS[:6]


def test_the_join_step_answers_the_pit_after_its_text_under_the_move_bar(
        monkeypatch):
    game = Game(pit_after_printing())
    sess = FakeSession(game, world_reads=0)
    run = _run(monkeypatch, sess, [])
    got = run.join("I")
    assert game.keys == PIT_KEYS and got["square"] == [1, 4, 2]


# --- the PARLAY bar as the Pit run drew it ---------------------------------------

#: Row 24 at the run's stop (`07-lost-join`): the heading glued to the first
#: word, HAUGHTY highlighted, with the speaker pick (the panel and its EXIT
#: row) and the text before the opening menu still drawn above it.
PARLAY_ROW = "PARLAY:HAUGHTY SLY NICE MEEK ABUSIVE"


def parlay_at_stop(lit_word: str) -> Screen:
    col = J.word_at(PARLAY_ROW, lit_word)
    return screen({10: " " * A.S.PARTY_COLUMN + "EXIT",
                   17: "THE FEMALE FIGHTER GASPS,",
                   18: "'THEY'RE BONDED!'", 19: "WHAT DO YOU DO?",
                   24: PARLAY_ROW}, (24, col, col + len(lit_word) - 1),
                  panel=("MATHEW", "MARK", "TRAVIS", "LEDERA", "SHARA",
                         "PHILIPPE"))


def test_a_heading_glued_to_its_first_word_is_split_off():
    assert J.word_at(PARLAY_ROW, "HAUGHTY") == 7
    assert J.word_at(PARLAY_ROW, "NICE") == 19
    assert J.word_at(PARLAY_ROW, "PARLAY:HAUGHTY") == -1
    assert J.bar_words(parlay_at_stop("HAUGHTY")) == (
        "HAUGHTY", "SLY", "NICE", "MEEK", "ABUSIVE")
    assert J.highlight(parlay_at_stop("HAUGHTY")) == 7


def test_the_parlay_bar_the_pit_run_stopped_on_is_answered_nice():
    # The run's keys up to the stop: continue, four rights to PARLAY, PARLAY,
    # the speaker; then this bar, which the step stopped on unanswered.
    script = pit_script()
    script[8] = (parlay_at_stop("HAUGHTY"), {RT: 9})
    script[9] = (parlay_at_stop("SLY"), {RT: 10, LT: 8})
    script[10] = (parlay_at_stop("NICE"), {R: 11, LT: 9})
    game = Game(script)
    got = game.answerer().run(PIT)
    assert game.keys[:7] == [R, RT, RT, RT, RT, R, R]
    assert game.keys == PIT_KEYS
    assert {"screen": "the bar HAUGHTY SLY NICE MEEK ABUSIVE",
            "row24": PARLAY_ROW} in got["screens"]
