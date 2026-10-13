"""The C64 Curse `fight` step in the Pit of Moander: its roll-square tour, the
wandering gate it holds while it walks, and the route choice by live area."""

from __future__ import annotations

from types import SimpleNamespace

import gamedata
import pytest

from tools.c64 import acceptance as A

MOVE_BAR = "I,J,K,M, RETURN OR BUTTON"
WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
SLUG_BAR = "ATTACK EVADE"


class FakeScreen:
    def __init__(self, rows):
        self._rows = rows

    def row(self, r):
        return self._rows[r]


class FakeGeo:
    """A 16x16 map: every square id 0 unless named in IDS, every edge solid
    unless named in OPEN as `(x, y, facing)` (both directions given)."""

    def __init__(self, ids, open_edges):
        self.ids = ids
        self.open = set(open_edges)

    def attributes(self, x, y):
        return self.ids.get((x, y), 0)

    def is_passable(self, x, y, facing):
        return (x, y, facing) in self.open


def both(x, y, facing):
    dx, dy = A.STEP[facing]
    return [(x, y, facing), (x + dx, y + dy, (facing + 2) % 4)]


#: The Pit's west corner as `GEO11` draws it: the join square 1,4 (id 5)
#: between three roll squares, and a script square 2,4 (id 4) east of it
#: leading to a roll square 2,3 that is reached only through 2,4.
CORNER = FakeGeo(
    {(1, 4): 5, (2, 4): 4},
    both(1, 4, 0) + both(1, 4, 3) + both(0, 4, 0) + both(1, 3, 3)
    + both(1, 4, 1) + both(2, 4, 0))


def test_the_tour_keeps_to_roll_squares_and_never_enters_a_script_square():
    tour = A.pit_tour(CORNER, (1, 4))
    assert tour == ((0, 3), (1, 3))
    reached = A.pit_distances(CORNER, (1, 4))
    assert (2, 4) not in reached and (2, 3) not in reached
    assert A.PitGeo(CORNER).is_passable(1, 4, 1) is False
    assert A.PitGeo(CORNER).is_passable(1, 4, 3) is True


def test_no_tour_when_fewer_than_two_joined_roll_squares_are_in_reach():
    lone = FakeGeo({(1, 4): 5}, both(1, 4, 0) + both(1, 4, 2))
    assert A.pit_tour(lone, (1, 4)) is None
    assert A.pit_tour(FakeGeo({}, []), (7, 7)) is None


@gamedata.needs_curse_disks
def test_the_pit_tour_from_the_join_corner_on_the_players_geo11():
    geo = A.curse_geo("GEO11", str(gamedata.curse_dir()))
    assert geo is not None
    assert A.pit_square_id(geo, 1, 4) == 5
    for start, want in (((1, 3), ((0, 4), (1, 3))), ((1, 4), ((0, 3), (1, 3)))):
        tour = A.pit_tour(geo, start)
        assert tour == want
        assert all(A.pit_square_id(geo, *sq) == 0 for sq in tour)


class PitSession:
    """A Pit walk that commits to a fight after COMMIT move keys, showing the
    slugs' `ATTACK EVADE` first when SLUGS; then one fight with OUTCOME, after
    which the machine is in DUNGEON idling in a key wait (a win) or in the
    party menu (a loss)."""

    def __init__(self, commit=4, slugs=False, outcome=A.S.WON, sticky_gate=False):
        self.memory = {A.CURSE_WANDER_GATE: 0, A.CURSE_SIDE: 3}
        self.gate_writes = []
        self.moves = []
        self.moves_at_commit = None
        self.commit, self.slugs, self.outcome = commit, slugs, outcome
        self.sticky_gate = sticky_gate
        self.attacked = False
        self.prep_reads = 2
        self.pressed = []
        self.fought = []
        self.idle_polls_after_fight = 0

    def asking(self):
        return self.slugs and len(self.moves) >= self.commit and not self.attacked

    def mode(self):
        if self.fought:
            return A.S.DUNGEON if self.outcome == A.S.WON else 0
        if len(self.moves) < self.commit or self.asking():
            return A.S.DUNGEON
        if self.moves_at_commit is None:
            self.moves_at_commit = len(self.moves)
        if self.prep_reads:
            self.prep_reads -= 1
            return A.COMBAT_PREP
        return A.S.COMBAT

    def key_idle(self):
        if self.fought:
            self.idle_polls_after_fight += 1
        return True

    def screen(self):
        if self.mode() != A.S.DUNGEON:
            return FakeScreen([""] * 25)
        bar = (WORLD_BAR if self.fought else SLUG_BAR if self.asking()
               else MOVE_BAR)
        return FakeScreen([""] * 24 + [bar])

    def press_bar(self, word, timeout=0):
        self.pressed.append(word)
        if word == A.CURSE_PIT_ATTACK and self.asking():
            self.attacked = True
        return True

    def press_kernal(self, code):
        self.pressed.append(code)

    def settle(self, seconds=1.0):
        pass

    def mon(self, timeout):
        sess = self

        class Mon:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, addr, n):
                return bytes([sess.memory.get(addr, 0)])

            def write(self, addr, data):
                sess.gate_writes.append((addr, data[0], sess.mode()))
                if not sess.sticky_gate:
                    sess.memory[addr] = data[0]

            def resume(self):
                pass

        return Mon()

    def await_bar(self, kinds, timeout=0, interval=0):
        return object()

    def fight(self, *, budget, tactic):
        self.fought.append(tactic)
        return A.S.FightResult(self.outcome, 3, 1.0, [], [])


def _pit_run(monkeypatch, tmp_path, sess, geo=CORNER, start=(1, 4)):
    from tools.c64 import laterbattle

    class Route:
        """`laterbattle.Battle`'s walk: a bar cleared and one forward key a
        square, asking `in_combat` before each, as `goto` does."""

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)
            self.last_goto_steps = 0

        def goto(self, target, budget, geo=None, accept=False):
            took = 0
            for _ in range(budget):
                took += 1
                if self.in_combat():
                    break
                self.clear_bar(accept)
                if self.in_combat():
                    break
                self.press("I")
            self.last_goto_steps = took
            return self.in_combat()

        def press(self, key):
            self.sess.moves.append(key)
            return True

        def clear_bar(self, accept=False):
            return None

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(A, "curse_geo", lambda name, disks: geo)
    events, captures = [], []
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess, run.out = sess, tmp_path
    run.staged_disk, run.disks = tmp_path / "s.D64", "unused"
    run.attack_by = ""
    run.log_bars, run.first_bar_key = False, None
    run.log = SimpleNamespace(emit=lambda kind, **kw: events.append((kind, kw)))
    run.capture = lambda tag, rows=None: captures.append(tag)
    run.to_world = lambda: True
    run.position = lambda: [*start, 0]
    run.key_idle = sess.key_idle
    run.reading = lambda: {}
    run.live_area = lambda: A.CURSE_PIT_AREA
    monkeypatch.setattr(A.S.Session, "melee_turn", lambda sess, bar: "MOVE")
    return run, events, captures


def test_a_pit_fight_holds_the_gate_answers_the_slugs_and_reads_the_side_at_the_first_bar(
        monkeypatch, tmp_path):
    sess = PitSession(slugs=True)
    run, events, captures = _pit_run(monkeypatch, tmp_path, sess)
    got = run.fight("300", "I", 40)
    assert sess.moves == ["I"] * 4 and sess.moves_at_commit == 4
    assert sess.pressed == [A.CURSE_PIT_ATTACK]
    assert sess.gate_writes == [(A.CURSE_WANDER_GATE, 0x80, A.S.DUNGEON),
                                (A.CURSE_WANDER_GATE, 0, A.S.DUNGEON)]
    assert got["wander_gate"] == {"address": "$4C2D", "was": 0, "now": 0x80,
                                  "script_idle": True, "restored": 0,
                                  "mode": A.S.DUNGEON}
    assert got["first_bar"] == {"seen": True, "side": 3}
    assert got["tour"] == [[0, 3], [1, 3]] and got["area"] == "GEO11"
    assert captures == ["fight-route", "fight-start", "first-bar", "fight-end"]
    assert [kw["word"] for kind, kw in events if kind == "pit-answer"] == ["ATTACK"]
    assert sess.idle_polls_after_fight >= 1


def test_the_gate_already_at_80_is_not_written_and_is_left_at_80(monkeypatch, tmp_path):
    sess = PitSession()
    sess.memory[A.CURSE_WANDER_GATE] = 0x80
    run, _, _ = _pit_run(monkeypatch, tmp_path, sess)
    got = run.fight("300", "I", 40)
    assert sess.gate_writes == [(A.CURSE_WANDER_GATE, 0x80, A.S.DUNGEON)]
    assert got["wander_gate"]["restored"] == 0x80


def test_a_lost_pit_fight_puts_the_gate_back_at_once(monkeypatch, tmp_path):
    sess = PitSession(outcome=A.S.LOST)
    run, events, _ = _pit_run(monkeypatch, tmp_path, sess)
    with pytest.raises(A.StepFailed, match="lost the fight"):
        run.fight("300", "I", 40)
    assert sess.memory[A.CURSE_WANDER_GATE] == 0
    assert sess.idle_polls_after_fight == 0
    last = [kw for kind, kw in events if kind == "wander-gate"][-1]
    assert last["restored"] == 0 and "script_idle" not in last


def test_a_pit_walk_with_no_fight_fails_and_puts_the_gate_back(monkeypatch, tmp_path):
    sess = PitSession(commit=10_000)
    run, _, captures = _pit_run(monkeypatch, tmp_path, sess)
    run.clock = iter(range(0, 10_000, 5)).__next__
    with pytest.raises(A.StepFailed, match="no fight in 12 steps of GEO11"):
        run.fight("300", "I", 12)
    assert len(sess.moves) == 12 and not sess.fought
    assert sess.memory[A.CURSE_WANDER_GATE] == 0
    assert "lost-fight" in captures


def test_a_gate_that_does_not_take_stops_the_step_before_any_move(monkeypatch, tmp_path):
    sess = PitSession(sticky_gate=True)
    run, _, _ = _pit_run(monkeypatch, tmp_path, sess)
    with pytest.raises(A.StepFailed, match=r"\$4C2D reads 0, not 128"):
        run.fight("300", "I", 40)
    assert sess.moves == []


def test_a_pit_corner_with_no_roll_squares_stops_before_the_gate(monkeypatch, tmp_path):
    sess = PitSession()
    lone = FakeGeo({(1, 4): 5}, [])
    run, _, _ = _pit_run(monkeypatch, tmp_path, sess, geo=lone)
    with pytest.raises(A.StepFailed, match="no two joined squares next to 1,4"):
        run.fight("300", "I", 40)
    assert sess.gate_writes == [] and sess.moves == []


def test_attack_by_is_not_offered_in_the_pit(monkeypatch, tmp_path):
    sess = PitSession()
    run, _, _ = _pit_run(monkeypatch, tmp_path, sess)
    run.attack_by = "ALIAS"
    with pytest.raises(A.StepFailed, match="tavern brawl only"):
        run.fight("300", "I", 40)
    assert sess.gate_writes == []


def test_the_tavern_route_plans_over_the_live_areas_map(monkeypatch, tmp_path):
    from tools.c64 import laterbattle
    from tools.curse_of_the_azure_bonds import cursethac0

    maps, goals = [], []
    tilverton = object()

    class Route:
        last_goto_steps = 2

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)

        def goto(self, target, steps, geo):
            goals.append((target, geo))
            return True

    class Session:
        def in_combat(self):
            return True

        def await_bar(self, *a, **k):
            return None

        def fight(self, *, budget, tactic):
            return A.S.FightResult("ended", 1, 1.0, [], [])

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(cursethac0, "area_geo",
                        lambda *a: pytest.fail("the staged save's map was read"))
    monkeypatch.setattr(A, "curse_geo",
                        lambda name, disks: maps.append(name) or tilverton)
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by, run.attack_owner = "", None
    run.attack_evidence = run.quit_evidence = None
    run.sess, run.out = Session(), tmp_path
    run.staged_disk, run.disks = tmp_path / "s.D64", "unused"
    run.to_world = lambda: True
    run.await_combat = lambda: True
    run.capture = lambda tag: None
    run.live_area = lambda: 1
    run.pit_fight = lambda *a, **k: pytest.fail("the Pit route was taken")
    got = run.fight("10", "I", 5)
    assert maps == ["GEO01"] and goals == [((6, 10), tilverton)]
    assert got["area"] == "GEO01"


def test_a_run_with_no_title_reads_no_live_area():
    run = A.CurseRun.__new__(A.CurseRun)
    assert run.live_area() is None
    run.game = SimpleNamespace(key="secret-of-the-silver-blades")
    assert run.live_area() is None
