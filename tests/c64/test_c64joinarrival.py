"""The C64 `join-arrival` step: a Fast Travel into the Silver Blades Compound
and SIR DERIC's arrival scene answered by its text, on fake screens."""

from __future__ import annotations

import types

import pytest

from goldbox.c64_port import SECRET_OF_THE_SILVER_BLADES as SILVER
from tests.c64.test_c64joinstep import CONTINUE, WORLD, Game, bar, screen
from tools.c64 import acceptance as A
from tools.c64 import joinstep as J

COMPOUND = J.site_for(SILVER.key, 0x44)
FIRST = "BE FRIENDLY ATTACK FLEE"
R, RT = J.RETURN, J.RIGHT
PARTY = ("GUY DE VALOIS", "PAINE", "EPONA", "MALACHITE", "DOMINIC", "MORGAINE")
#: The world panel's heading row and the first member's row.
HEAD, FIRST_ROW = 2, 3
NAME_FIELD = 15


def world(names: tuple[str, ...]) -> object:
    """The world bar over a panel listing NAMES under its `NAME AC HP`
    heading, each with an AC and hit points beside the name field."""
    col = A.S.PARTY_COLUMN
    rows = {HEAD: " " * col + "NAME".ljust(NAME_FIELD) + "AC HP"}
    for i, name in enumerate(names):
        rows[FIRST_ROW + i] = " " * col + name.ljust(NAME_FIELD) + " 5 20"
    rows[24] = WORLD
    return screen(rows, (24, 0, 3))


def compound_script(answer_no: bool = False,
                    party: tuple[str, ...] = PARTY) -> list:
    """The scene as `ECL44 $8066`-`$8170` draws it: the menu, a continue
    bar, the yes/no, then the world bar with SIR DERIC on the panel."""
    return [
        (bar(FIRST, "BE FRIENDLY"), {R: 1, RT: 1}),                # 0
        (screen({24: CONTINUE}), {R: 2}),                          # 1
        (bar("YES NO", "YES"), {R: 4 if not answer_no else 5}),    # 2
        (screen({}), {}),                                          # 3
        (world(party + ("SIR DERIC",)), {}),                       # 4
        (world(party), {}),                                        # 5
    ]


class Target:
    """`SessTarget` over the fake session: the trip subclasses it."""

    def __init__(self, sess):
        self.sess = sess

    def set_pc(self, address):
        pass


class FakeSession:
    """A party in New Verdigris (area `$10`) on the world bar; the trip puts
    the scene up and moves the area byte to the Compound."""

    def __init__(self, game: Game, gate: int = 0, party=PARTY):
        self.game = game
        self.area = 0x10
        self.party = party
        self.travelled = False
        self.memory = {0x4C9E: gate}
        self.reads: list[int] = []

    def screen(self):
        if not self.travelled:
            return world(self.party)
        return self.game.screen()

    def press_kernal(self, key):
        self.game.press(key)

    def stable_party_rows(self):
        shown = self.screen()
        width = NAME_FIELD
        col = A.S.PARTY_COLUMN
        return [r for r in range(FIRST_ROW, 12)
                if shown.row(r)[col:col + width].strip()]

    def handle_prompt(self, s=None):
        return False

    def mon(self, timeout=5.0):
        sess = self

        class Monitor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, addr, length):
                sess.reads.append(addr)
                return bytes(sess.memory.get(addr + i, 0) for i in range(length))

            def resume(self):
                pass

        return Monitor()


def _run(monkeypatch, sess, trips):
    run = A.SilverRun.__new__(A.SilverRun)
    run.sess, run.game = sess, SILVER
    run.to_world = lambda tries=10: True
    run.capture = lambda tag, rows=None: []
    run.position = lambda: [7, 15, 0]
    run.log = type("L", (), {"say": staticmethod(lambda text: None),
                             "emit": staticmethod(lambda *a, **k: None)})()
    run.fail = lambda tag, why: A.StepFailed(why)
    monkeypatch.setattr(A, "SessTarget", Target)
    monkeypatch.setattr(A.auto_actions.FastTravel, "current_area",
                        staticmethod(lambda target, addresses=None:
                                     target.sess.area))

    def trip(tag, area, ready=None):
        trips.append((tag, area))
        sess.travelled, sess.area = True, area
        return {"area": area, "areas_seen": [0x10, area]}

    run.trip = trip
    real = J.JoinAnswerer

    def answerer(screen_fn, press, **kw):
        kw.update(clock=sess.game.clock, sleep=sess.game.sleep)
        return real(screen_fn, press, **kw)

    monkeypatch.setattr(A.joinstep, "JoinAnswerer", answerer)
    return run


def test_the_compound_site_is_read_from_ecl44_and_joins_on_arrival():
    assert COMPOUND.script == "ECL44" and COMPOUND.joins == ("SIR DERIC",)
    assert COMPOUND.arrival and COMPOUND.first_visit == (0x4C9E, 0x01)
    first, yes = COMPOUND.screens
    # BE FRIENDLY is index 0 of `$80CE`'s menu, the arm to `$80FA`; YES is
    # index 0 of `$9970`, and only index 1 branches away from the ADDNPC.
    assert first.words == ("BE", "FRIENDLY", "ATTACK", "FLEE")
    assert first.answer == "BE FRIENDLY"
    assert yes.words == ("YES", "NO") and yes.answer == "YES"
    assert J.site_for(SILVER.key, 0x32) is None


def test_join_arrival_travels_then_answers_the_scene(monkeypatch):
    game = Game(compound_script())
    sess = FakeSession(game)
    trips: list = []
    run = _run(monkeypatch, sess, trips)
    got = run.join_arrival("68")
    assert trips == [("join-arrival", 0x44)]
    assert game.keys == [R, R, R]
    assert got["joins"] == ["SIR DERIC"] and got["area"] == 0x44
    assert got["first_visit"] == {"address": "$4C9E", "mask": 1, "read": 0}
    assert got["trip"]["areas_seen"] == [0x10, 0x44]
    assert any(row.startswith("SIR DERIC") for row in got["panel"])


PROMPT = screen({18: "INSERT SIDE D", 24: "PRESS ANY KEY TO CONTINUE"})


def test_the_trip_hands_over_at_the_join_menu_outside_the_key_window(
        monkeypatch):
    """Run `e231406cb5-s2-sir-deric-join`: the trip, a disk prompt the
    session answers while it settles, then the Compound's menu, with the
    program counter never in either key window.  The real `trip` ends on
    that menu and the scene is answered."""
    game = Game(compound_script())
    sess = FakeSession(game)
    run = _run(monkeypatch, sess, [])
    del run.trip                          # the real one, through FastTravel
    run.clock = game.clock
    run.budget = lambda timeout, what: None
    run.sess.prompting = 0

    def settle(seconds=0):
        game.now += seconds
        sess.prompting = max(0, sess.prompting - 1)

    sess.settle = settle
    shown = sess.screen
    sess.screen = lambda: PROMPT if sess.prompting else shown()

    class Registers(FakeSession.mon(sess).__class__):
        def registers(self):
            return {3: 0x6A00}            # in neither key window

    sess.mon = lambda timeout=5.0: Registers()
    monkeypatch.setattr(A.auto_actions, "pc_register", lambda m: 3)
    monkeypatch.setattr(A.auto_actions.FastTravel, "legality",
                        lambda self, target, row: types.SimpleNamespace(
                            ok=True, reason=""))

    def travel(self, target, area=None, **kw):
        sess.travelled, sess.area, sess.prompting = True, area.id, 2
        return A.auto_actions.Outcome(True, "Traveling.", ())

    monkeypatch.setattr(A.auto_actions.FastTravel, "run", travel)
    got = run.join_arrival("68")
    assert got["trip"]["areas_seen"] == [0x10, 0x44]
    assert game.keys == [R, R, R]
    assert game.now < A.WARP_IDLE_SECONDS


def test_join_arrival_from_inside_the_area_travels_nowhere(monkeypatch):
    game = Game(compound_script())
    sess = FakeSession(game)
    sess.area = 0x44
    trips: list = []
    run = _run(monkeypatch, sess, trips)
    with pytest.raises(A.StepFailed, match="already in area 68"):
        run.join_arrival("68")
    assert trips == [] and sess.reads == [] and game.keys == []


def test_join_arrival_with_him_in_the_party_travels_nowhere(monkeypatch):
    game = Game(compound_script())
    sess = FakeSession(game, party=PARTY[:5] + ("SIR DERIC",))
    trips: list = []
    run = _run(monkeypatch, sess, trips)
    with pytest.raises(A.StepFailed, match="SIR DERIC already in the party"):
        run.join_arrival("68")
    assert trips == [] and sess.reads == [] and game.keys == []


def test_join_arrival_with_a_full_party_travels_nowhere(monkeypatch):
    game = Game(compound_script())
    sess = FakeSession(game, party=PARTY + ("ARIEL", "BRUTUS"))
    trips: list = []
    run = _run(monkeypatch, sess, trips)
    with pytest.raises(A.StepFailed, match="the panel lists 8"):
        run.join_arrival("68")
    assert trips == [] and sess.reads == [] and game.keys == []


def test_a_longer_name_holding_his_is_not_him(monkeypatch):
    """`SIR DERICSON` neither stops the step before the trip nor stands in
    for SIR DERIC after it: the whole name field is compared."""
    party = PARTY[:5] + ("SIR DERICSON",)
    game = Game(compound_script(answer_no=True, party=party))
    sess = FakeSession(game, party=party)
    trips: list = []
    run = _run(monkeypatch, sess, trips)
    with pytest.raises(A.StepFailed, match="does not list SIR DERIC"):
        run.join_arrival("68")
    assert trips == [("join-arrival", 0x44)]


def test_join_arrival_with_the_scene_played_travels_nowhere(monkeypatch):
    game = Game(compound_script())
    sess = FakeSession(game, gate=0x01)
    trips: list = []
    run = _run(monkeypatch, sess, trips)
    with pytest.raises(A.StepFailed, match=r"\$4C9E reads \$01"):
        run.join_arrival("68")
    assert trips == [] and game.keys == [] and sess.reads == [0x4C9E]


def test_join_arrival_fails_when_he_is_not_on_the_panel_after(monkeypatch):
    game = Game(compound_script(answer_no=True))
    sess = FakeSession(game)
    run = _run(monkeypatch, sess, [])
    with pytest.raises(A.StepFailed, match="does not list SIR DERIC"):
        run.join_arrival("68")


def test_join_arrival_in_an_area_with_no_arrival_join_travels_nowhere(monkeypatch):
    game = Game(compound_script())
    sess = FakeSession(game)
    trips: list = []
    run = _run(monkeypatch, sess, trips)
    with pytest.raises(A.StepFailed, match="no arrival join in area 16"):
        run.join_arrival("16")
    assert trips == [] and sess.reads == []


def test_join_arrival_parses_an_area_and_is_silver_blades_only(tmp_path, capsys):
    steps = A.parse_steps(["load", "join-arrival 68", "save"])
    assert steps[1] == A.Step("join-arrival", "68")
    for bad in ("join-arrival", "join-arrival x"):
        with pytest.raises(ValueError):
            A.parse_steps(["load", bad])
    with pytest.raises(SystemExit):
        A.main(["--title", "curse", "--save", str(tmp_path / "x.d64"),
                "--steps", "load", "join-arrival 68", "--out", str(tmp_path)])
    assert ("the join-arrival step: Secret of the Silver Blades only"
            in capsys.readouterr().err)


def test_the_warp_step_and_join_arrival_share_one_trip(monkeypatch):
    run = A.CurseRun.__new__(A.CurseRun)
    run.game = A.c64_port.CURSE_OF_THE_AZURE_BONDS
    run.fail = lambda tag, why: A.StepFailed(why)
    seen = []
    run.trip = lambda tag, area: seen.append((tag, area)) or {"area": area}
    assert run.warp("1") == {"area": 1} and seen == [("warp", 1)]
