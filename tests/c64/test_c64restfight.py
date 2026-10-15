"""The C64 `rest-fight` step: Silver Blades' Compound patrol, met by resting.

The screens are the rows of run `5a169821a3-f1-c64-compound-rest`
(`load`, `walk I`, `rest 240h` on the S3 C64 save): the patrol's page as the
rest stopped (`03-rested-240h.txt`) and the `COM.PREP` screen a Return later
(`04-lost-rest.txt`), rows 16 to 24; the rows above are blank frame.  The
command bar of another member is run `8d53cd75ea-s4-c64-patrol-fight`'s
`04-first-bar.txt` whole: MALACHITE's turn, her name on the panel's row 2;
and run `b0b41a61be-f2-c64-sir-deric-view`'s, MORGAINE's turn, with SIR DERIC
in view.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

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


MORGAINE_BAR = [
    '@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@',
    "$&'(&'(   ....        $                $",
    '%)*+)*+    ....       %MORGAINE        %',
    '%,-.,-.     ....      %                %',
    "%...89:&'(   ....     %HIT POINTS 35   %",
    '%...;<=)*+    ....    %                %',
    '%...>?.,-.     ....   %AC 7            %',
    '%.  KLM......BCD....  %                %',
    '%.. NOP......EFG .... %                %',
    '%...QRS....@AHIJ  ....%                %',
    '%....     ......]^_...%                %',
    '% ....    ...... !" ..%                %',
    '%  ....   ......#$%  .%                %',
    '%.....................%                %',
    '%.....................%                %',
    '%.....................%                %',
    '%      ....           %                %',
    '%       ....          %                %',
    '%        ....         %                %',
    '%         ....        %                %',
    '%          ....       %                %',
    '%           ....      %                %',
    '&                     &                &',
    '@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@',
    'MOVE VIEW AIM QUICK DONE',
]
#: The aim bar, with MANUAL on it: not captured (the live run found SIR
#: DERIC already in view and took no AIM), so its words are Pool's.
AIM_BAR = MORGAINE_BAR[:24] + ["NEXT PREV MANUAL TARGET CENTER EXIT"]
MANUAL_BAR = MORGAINE_BAR[:24] + ["EXIT"]
SCREENS.update(morgaine=MORGAINE_BAR, aim=AIM_BAR, manual=MANUAL_BAR)
MODES.update(morgaine=A.S.COMBAT, aim=A.S.COMBAT, manual=A.S.COMBAT)

#: The save's party slots; SIR DERIC is slot 7 (run
#: `b0b41a61be-f2-c64-sir-deric-view`, `rest-fight-view`).
SLOTS = {"SIR DERIC": 7, "GUY DE VALOIS": 0, "PAINE": 1, "EPONA": 2,
         "MALACHITE": 3, "DOMINIC": 4, "MORGAINE": 5}


class _Fight(_Session):
    """`_Session` in the fight: the position table holds SIR DERIC at
    `square` under the camera; AIM, MANUAL and EXIT move the bars, and a
    joystick key on the manual bar moves the camera one square when
    `follows`."""

    def __init__(self, camera, square=(30, 14), name="SIR DERIC", follows=True):
        super().__init__("world", {("patrol", 0x0D): "prep"},
                         later={"prep": (1, "morgaine")})
        self.camera, self.square, self.name = list(camera), square, name
        self.follows = follows
        self.turns = {"morgaine": "monster"}

    def battle(self):
        him = SimpleNamespace(index=7, x=self.square[0], y=self.square[1],
                              name=self.name, square=tuple(self.square))
        other = SimpleNamespace(index=5, x=27, y=14, name="MORGAINE",
                                square=(27, 14))
        return SimpleNamespace(camera=tuple(self.camera), combatants=(other, him))

    def combat_bar(self, label, timeout=0):
        self.sent.append(("bar", label))
        if (self.state, label) != ("morgaine", "AIM"):
            return False
        self.state = "aim"
        return True

    def select_bar(self, label, row=24, timeout=0):
        self.sent.append(("bar", label))
        moves = {("aim", "MANUAL"): "manual", ("aim", "EXIT"): "morgaine",
                 ("manual", "EXIT"): "aim"}
        if (self.state, label) not in moves:
            return False
        self.state = moves[(self.state, label)]
        return True


class _Keys(_Keyboard):
    def __init__(self, fight):
        self.fight = fight

    def key(self, name, *timing):
        f = self.fight
        f.sent.append(("joy", name))
        assert f.state == "manual", f"a joystick key on {f.state}"
        if f.follows:
            dx, dy = next(k for k, v in A.VIEW_KEYS.items() if v == name)
            f.camera[0] += dx
            f.camera[1] += dy


def _view(tmp_path, monkeypatch, fight):
    fight.kbd = _Keys(fight)
    run = _run(tmp_path, monkeypatch, fight)
    run.staged_disk = tmp_path / "staged.D64"
    monkeypatch.setattr(A, "saved_characters",
                        lambda path: {n: {"owner": o} for n, o in SLOTS.items()})
    return run


def test_sir_deric_already_in_view_is_captured_with_no_aim(tmp_path, monkeypatch):
    """The live run: MORGAINE's bar first, the camera at 25,11 and SIR DERIC
    (slot 7) at 30,14, inside the seven-square window, so the frame is kept
    as it stands and the turn is passed with DONE and GUARD, never QUICK."""
    fight = _Fight((25, 11))
    run = _view(tmp_path, monkeypatch, fight)
    got = run.patrol_fight("240h SIR DERIC")
    run.log.close()
    assert fight.sent == [("bar", "ENCAMP"), ("rest", 240, 0), ("key", 0x0D),
                          ("turn", "morgaine")]
    assert got["in_view"]["slot"] == 7 and got["in_view"]["square"] == [30, 14]
    assert got["in_view"]["camera"] == [25, 11] and got["in_view"]["aim_bar"] is None
    assert len(list(tmp_path.glob("*-in-view-SIR-DERIC.png"))) == 1


def test_sir_deric_out_of_view_is_brought_in_with_aim_and_exited(
        tmp_path, monkeypatch):
    """Camera three squares short: AIM, MANUAL, joystick keys east until his
    square is in the window, the frame kept, then EXIT twice back to the
    command bar with no action taken, and the turn passed."""
    fight = _Fight((21, 11))
    run = _view(tmp_path, monkeypatch, fight)
    got = run.patrol_fight("240h SIR DERIC")
    run.log.close()
    assert fight.sent == [("bar", "ENCAMP"), ("rest", 240, 0), ("key", 0x0D),
                          ("bar", "AIM"), ("bar", "MANUAL"),
                          ("joy", "KP_6"), ("joy", "KP_6"), ("joy", "KP_6"),
                          ("bar", "EXIT"), ("bar", "EXIT"), ("turn", "morgaine")]
    assert got["in_view"]["camera"] == [24, 11]
    assert [m["key"] for m in got["in_view"]["moves"]] == ["KP_6"] * 3


def test_a_view_that_never_reaches_him_fails_with_the_aim_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "VIEW_PRESSES", 4)
    fight = _Fight((5, 11), follows=False)
    run = _view(tmp_path, monkeypatch, fight)
    with pytest.raises(A.StepFailed, match="did not come into view"):
        run.patrol_fight("240h SIR DERIC")
    run.log.close()
    assert fight.sent.count(("joy", "KP_6")) == 4
    assert ("turn", "morgaine") not in fight.sent and fight.state == "manual"


def test_a_slot_whose_record_is_not_his_takes_no_aim(tmp_path, monkeypatch):
    """Found by slot, checked by the record's name in memory: a slot holding
    somebody else fails before any AIM."""
    fight = _Fight((5, 11), name="DOMINIC")
    run = _view(tmp_path, monkeypatch, fight)
    with pytest.raises(A.StepFailed, match="combatant 7 is 'DOMINIC'"):
        run.patrol_fight("240h SIR DERIC")
    run.log.close()
    assert fight.sent == [("bar", "ENCAMP"), ("rest", 240, 0), ("key", 0x0D)]


def test_a_name_not_in_the_party_rests_not_at_all(tmp_path, monkeypatch):
    fight = _Fight((25, 11))
    run = _view(tmp_path, monkeypatch, fight)
    with pytest.raises(A.StepFailed, match="SIR DERICSON is not in the party"):
        run.patrol_fight("240h SIR DERICSON")
    run.log.close()
    assert fight.sent == []


def test_the_view_window_and_the_key_toward_a_square():
    assert A.in_view((25, 11), (30, 14)) and A.in_view((25, 11), (31, 17))
    assert not A.in_view((25, 11), (32, 14)) and not A.in_view((25, 11), (30, 10))
    assert A.toward((21, 11), (30, 14)) == "KP_6"
    assert A.toward((25, 20), (30, 14)) == "KP_9"


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
