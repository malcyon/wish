"""The C64 `rest-fight` step: Silver Blades' Compound patrol, met by resting.

The screens are the rows of run `5a169821a3-f1-c64-compound-rest`
(`load`, `walk I`, `rest 240h` on the S3 C64 save): the patrol's page as the
rest stopped (`03-rested-240h.txt`) and the `COM.PREP` screen a Return later
(`04-lost-rest.txt`), rows 16 to 24; the rows above are blank frame.  The
command bar of another member is run `8d53cd75ea-s4-c64-patrol-fight`'s
`04-first-bar.txt` whole: MALACHITE's turn, her name on the panel's row 2.
"""

from __future__ import annotations

import pathlib

import pytest

from tools.c64 import acceptance as A

BLANK = "%" + " " * 38 + "%"
#: Rows 16-24 of the patrol page, as captured.
PATROL_ROWS = [
    "@" * 40,
    "$YOU ARE SPOTTED BY A PATROL.          $",
    BLANK, BLANK, BLANK, BLANK,
    "&" + " " * 38 + "&",
    "@" * 40,
    "PRESS BUTTON OR RETURN TO CONTINUE.",
]
#: Rows 16-24 of `COM.PREP`'s screen, as captured: frame, row 24 blank.
PREP_ROWS = ["%                     %                %"] * 6 + [
    "&                     &                &", "@" * 40, ""]
COMMAND_BAR = "MOVE VIEW AIM USE QUICK DONE"
BLACK_CIRCLE_ROWS = list(PATROL_ROWS)
BLACK_CIRCLE_ROWS[1] = "$THE BLACK CIRCLE SENDS MONSTERS       $"


def _screen(lower: list[str]) -> list[str]:
    return [BLANK] * 16 + list(lower)


MALACHITE_BAR = [
    '@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@',
    '$...89:   ....        $                $',
    '%...;<=    ....       %MALACHITE       %',
    '%...>?.     ....      %                %',
    "%   &'(&'(   ....     %HIT POINTS 58   %",
    '%   )*+)*+    ....    %                %',
    '%   ,-.,-.     ....   %AC 7            %',
    "%.  ...89:&'(   ....  %                %",
    '%.. ...;<=)*+    .... %                %',
    '%......>?.,-.     ....%                %',
    '%....  KLM            %                %',
    '% .... NOP            %                %',
    '%  ....QRS            %                %',
    '%                     %                %',
    '%                     %                %',
    '%                     %                %',
    '%                     %                %',
    '%                     %                %',
    '%                     %                %',
    '%                     %                %',
    '%                     %                %',
    '%                     %                %',
    '&                     &                &',
    '@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@',
    'MOVE VIEW AIM QUICK DONE',
]
#: The same frame on SIR DERIC's turn: his name where hers was.
DERIC_BAR = list(MALACHITE_BAR)
DERIC_BAR[2] = MALACHITE_BAR[2].replace("MALACHITE", "SIR DERIC")

SCREENS = {
    "world": _screen([BLANK] * 8 + ["MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"]),
    "camp": _screen([BLANK] * 8 + ["REST ALTER FIX VIEW MAGIC SAVE EXIT"]),
    "patrol": _screen(PATROL_ROWS),
    "circle": _screen(BLACK_CIRCLE_ROWS),
    "prep": _screen(PREP_ROWS),
    "command": _screen(PREP_ROWS[:-1] + [COMMAND_BAR]),
    "malachite": MALACHITE_BAR,
    "deric": DERIC_BAR,
    "monster": MALACHITE_BAR[:24] + [""],
}
#: LINKER's mode byte in each state.
MODES = {"world": A.S.DUNGEON, "camp": A.S.DUNGEON, "patrol": A.S.DUNGEON,
         "circle": A.S.DUNGEON, "prep": A.COMBAT_PREP, "command": A.S.COMBAT,
         "malachite": A.S.COMBAT, "deric": A.S.COMBAT, "monster": A.S.COMBAT}


class _Screen:
    def __init__(self, rows):
        self._rows = rows

    def row(self, r):
        return self._rows[r]


class _Keyboard:
    def screenshot(self, path, **kw):
        pathlib.Path(path).write_bytes(b"")
        return True


class _Session:
    """The Compound's screens, moved by Return and by the game itself:
    `later` replaces a state after that many reads with no key."""

    def __init__(self, start, moves, later=None):
        self.state, self.moves, self.later = start, moves, dict(later or {})
        self.sent, self.reads = [], 0
        self.kbd = _Keyboard()
        #: Where `combat_turn` (DONE, then GUARD) leaves each state.
        self.turns: dict = {}

    def screen(self):
        if self.state in self.later:
            reads, following = self.later[self.state]
            self.reads += 1
            if self.reads > reads:
                self.state, self.reads = following, 0
        return _Screen(SCREENS[self.state])

    def press_kernal(self, code):
        self.sent.append(("key", code))
        key = (self.state, code)
        assert key in self.moves, f"no transition for {key}"
        self.state = self.moves[key]
        return True

    def in_combat(self):
        return MODES[self.state] == A.S.COMBAT

    def mode(self):
        self.screen()
        return MODES[self.state]

    def await_bar(self, bars, timeout=0, interval=0):
        for _ in range(5):
            if {"AIM", "DONE"} <= set(self.screen().row(24).split()):
                return COMMAND_BAR
        return None

    def combat_turn(self):
        self.sent.append(("turn", self.state))
        assert self.state in self.turns, f"no turn passes from {self.state}"
        self.state = self.turns[self.state]
        return "GUARD"

    def handle_prompt(self, s=None):
        return False

    def settle(self, seconds=0):
        pass


#: The Compound, area $44: the only area the step rests in.
COMPOUND = 0x44


def _run(tmp_path, monkeypatch, sess, *, area=COMPOUND,
         interrupted=True, text=("YOU ARE SPOTTED BY A PATROL.",), stop="patrol"):
    """A Silver Blades run on SESS; the rest stops on STOP after eight hours."""
    monkeypatch.setattr(A, "REST_LEAVE_SECONDS", 2)
    monkeypatch.setattr(A, "ARRIVAL_PAGE_SECONDS", 0.5)
    monkeypatch.setattr(A, "SILVER_PREP_SECONDS", 5)

    def fake_rest(s, log, minutes, hours, cp, quiet=False):
        assert quiet is False
        s.sent.append(("rest", hours, minutes))
        got = {"before": {"clock": [0, 9, 2, 4, 0, 0]},
               "after": {"clock": [0, 9, 2, 12, 0, 0]},
               "rest_interrupt": [96, 20]}
        if interrupted:
            s.state = stop
            got.update(ended="interrupted", interrupted=True,
                       bar=SCREENS[stop][24], text=list(text))
        else:
            got.update(ended="completed", interrupted=False)
        return got

    monkeypatch.setattr(A.route_pool, "rest", fake_rest)
    run = A.SilverRun.__new__(A.SilverRun)
    run.sess, run.out, run.log = sess, tmp_path, A.Log(tmp_path)
    run.shots, run.armed = 0, {}
    run.game = A.c64_port.SECRET_OF_THE_SILVER_BLADES

    def to_world(tries=10):
        return sess.state == "world"

    def to_camp():
        sess.sent.append(("bar", "ENCAMP"))
        sess.state = "camp"
        return True

    monkeypatch.setattr(run, "to_world", to_world)
    monkeypatch.setattr(run, "to_camp", to_camp)
    monkeypatch.setattr(run, "position", lambda: [7, 14, 0])
    monkeypatch.setattr(run, "area_now", lambda: area)
    return run


def test_the_patrol_page_is_answered_once_and_the_first_bar_is_captured(
        tmp_path, monkeypatch):
    """The live sequence: the rest stops on the patrol's page, one Return,
    `COM.PREP`'s blank row 24, then the command bar, which is captured as
    `first-bar` with nothing pressed after the Return."""
    sess = _Session("world", {("patrol", 0x0D): "prep"},
                    later={"prep": (2, "command")})
    run = _run(tmp_path, monkeypatch, sess)
    got = run.patrol_fight("240h")
    run.log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("rest", 240, 0), ("key", 0x0D)]
    assert got["area"] == COMPOUND == A.REST_FIGHT_AREA
    assert got["pages"] == ["PRESS BUTTON OR RETURN TO CONTINUE."]
    assert got["text"] == ["YOU ARE SPOTTED BY A PATROL."]
    assert got["first_bar"]["bar"] == COMMAND_BAR
    assert got["rest_interrupt"] == [96, 20]
    first = sorted(tmp_path.glob("*-first-bar.txt"))
    assert len(first) == 1 and COMMAND_BAR in first[0].read_text()


def test_a_fight_found_over_the_patrol_page_needs_no_key(tmp_path, monkeypatch):
    """The rest's own read already kept the patrol's text and the game went
    on to `COM.PREP` by itself: no Return is sent."""
    sess = _Session("world", {}, later={"prep": (1, "command")})
    run = _run(tmp_path, monkeypatch, sess, stop="prep")
    got = run.patrol_fight("240h")
    run.log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("rest", 240, 0)]
    assert got["pages"] == [] and got["first_bar"]["bar"] == COMMAND_BAR


def test_a_rest_that_runs_its_time_fails_with_no_key_after_it(tmp_path, monkeypatch):
    sess = _Session("world", {})
    run = _run(tmp_path, monkeypatch, sess, interrupted=False)
    with pytest.raises(A.StepFailed, match="no fight in 240h of rest"):
        run.patrol_fight("240h")
    run.log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("rest", 240, 0)]


def test_a_party_outside_the_compound_is_stopped_before_any_key(tmp_path, monkeypatch):
    sess = _Session("world", {})
    run = _run(tmp_path, monkeypatch, sess, area=0x10)
    with pytest.raises(A.StepFailed, match="area 16, not 68; nothing was pressed"):
        run.patrol_fight("240h")
    run.log.close()
    assert sess.sent == []


def test_a_page_that_is_not_the_patrol_gets_no_key(tmp_path, monkeypatch):
    sess = _Session("world", {})
    run = _run(tmp_path, monkeypatch, sess, stop="circle",
               text=("THE BLACK CIRCLE SENDS MONSTERS",))
    with pytest.raises(A.StepFailed, match="not the patrol; nothing pressed"):
        run.patrol_fight("240h")
    run.log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("rest", 240, 0)]


def test_the_camp_bar_after_the_page_fails_as_no_fight(tmp_path, monkeypatch):
    sess = _Session("world", {("patrol", 0x0D): "camp"})
    run = _run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="with no fight"):
        run.patrol_fight("240h")
    run.log.close()


def test_rest_fight_parses_hours_and_must_end_the_run():
    steps = A.parse_steps(["load", "rest-fight 240h"])
    assert steps[-1] == A.Step("rest-fight", "240h")
    with pytest.raises(ValueError, match="last step"):
        A.parse_steps(["load", "rest-fight 8h", "save"])
    with pytest.raises(ValueError, match="needs an argument"):
        A.parse_steps(["load", "rest-fight"])
    with pytest.raises(ValueError, match="rest"):
        A.parse_steps(["load", "rest-fight soon"])


PARTY = ["SIR DERIC", "Guy de Valois", "PAINE", "EPONA", "MALACHITE",
         "DOMINIC", "MORGAINE"]


def _named(tmp_path, monkeypatch, turns, later=None, first="malachite"):
    """The patrol fight opening on FIRST's bar, every passed turn moved by TURNS."""
    sess = _Session("world", {("patrol", 0x0D): "prep"},
                    later={"prep": (1, first), **(later or {})})
    sess.turns = turns
    run = _run(tmp_path, monkeypatch, sess)
    run.names = PARTY
    monkeypatch.setattr(A, "MEMBER_BAR_CHANGE", 0.5)
    return run, sess


def test_other_members_bars_are_passed_with_done_until_sir_deric_s_own(
        tmp_path, monkeypatch):
    """The live opening: MALACHITE's bar first.  Her turn is passed with
    DONE (never QUICK), a monster's turn is waited out with no key, and SIR
    DERIC's bar is captured whole with nothing pressed on it."""
    run, sess = _named(tmp_path, monkeypatch, {"malachite": "monster"},
                       later={"monster": (2, "deric")})
    got = run.patrol_fight("240h SIR DERIC")
    run.log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("rest", 240, 0), ("key", 0x0D),
                         ("turn", "malachite")]
    assert got["first_bar"]["acting"] == "MALACHITE"
    assert got["member_bar"]["who"] == "SIR DERIC"
    assert got["member_bar"]["passed"] == ["MALACHITE"]
    kept = (tmp_path / sorted(p.name for p in tmp_path.glob("*-member-bar-SIR-DERIC.txt"))[0])
    assert "SIR DERIC" in kept.read_text().split("\n")[2]
    assert sess.state == "deric"


def test_a_first_bar_that_is_already_his_presses_nothing(tmp_path, monkeypatch):
    run, sess = _named(tmp_path, monkeypatch, {}, first="deric")
    got = run.patrol_fight("240h sir  deric")
    run.log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("rest", 240, 0), ("key", 0x0D)]
    assert got["member_bar"]["passed"] == []


def test_a_fight_that_ends_before_his_bar_fails_with_the_screen_kept(
        tmp_path, monkeypatch):
    run, sess = _named(tmp_path, monkeypatch, {"malachite": "world"})
    with pytest.raises(A.StepFailed, match="fight ended before SIR DERIC's bar"):
        run.patrol_fight("240h SIR DERIC")
    run.log.close()
    assert sess.sent[-1] == ("turn", "malachite")


def test_a_name_not_in_the_party_rests_not_at_all(tmp_path, monkeypatch):
    run, sess = _named(tmp_path, monkeypatch, {})
    with pytest.raises(A.StepFailed, match="SIR DERICSON is not in the party"):
        run.patrol_fight("240h SIR DERICSON")
    run.log.close()
    assert sess.sent == []


def test_rest_fight_takes_a_member_after_the_duration():
    steps = A.parse_steps(["load", "rest-fight 240h SIR DERIC"])
    assert steps[-1] == A.Step("rest-fight", "240h SIR DERIC")
    assert A.parse_rest_fight("240h sir deric") == ("240h", "SIR DERIC")
    assert A.parse_rest_fight("8h") == ("8h", None)


def test_a_party_outside_the_compound_is_not_sent_to_the_world_bar(
        tmp_path, monkeypatch):
    """`to_world` answers a page still drawn; outside the Compound that page
    is not the step's, so the area is read first and nothing is pressed."""
    sess = _Session("patrol", {})
    run = _run(tmp_path, monkeypatch, sess, area=0x10)
    called = []
    monkeypatch.setattr(run, "to_world", lambda tries=10: called.append(1) or True)
    with pytest.raises(A.StepFailed, match="nothing was pressed"):
        run.patrol_fight("240h")
    run.log.close()
    assert called == [] and sess.sent == []
