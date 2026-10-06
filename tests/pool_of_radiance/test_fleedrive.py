"""The third fight outcome, and the tactic that produced it.

`tools/c64/session.py` classified two of the engine's three end-of-fight lines
until 2026-09-08. The third, `THE PARTY RUNS AWAY`, was read off a driven
flight that night -- `cited/445/run2`, `tools/pool_of_radiance/fleedrive.py drive
--no-wound`, where ROLAND walked to the edge of the combat map, stepped off
it, and the game answered `GOT AWAY` and wrote `$86 RUNNING` into his record
(`#445`).

Nothing here needs an emulator. `FakeSession` and its screens come from
`tests/pool_of_radiance/test_combatdrive.py`, which is where the fight loop is tested; the
arena `step_to_edge` walks is `tests/gamedata.py`'s `synthetic_arena`, built
from the documented format and the player's own saved characters.
"""

import pytest
from conftest import load_tools_module
from gamedata import synthetic_arena
from support.combatdrive import (
    COMBAT,
    DUNGEON,
    STATUS,
    FakeScreen,
    FakeSession,
    command_bar,
)

from automap import combat  # noqa: E402
from automap.target import MemoryTarget  # noqa: E402

session = load_tools_module("session")
fleedrive = load_tools_module("fleedrive")

RAN = session.RAN
RAN_TEXT = session.RAN_TEXT


# -- the outcome the driver now names ---------------------------------------


def test_a_fight_the_party_runs_away_from_is_classified_from_the_screen():
    """The fleeing branch, against the row a driven flight actually drew.

    `cited/445/run2/screens.txt` at +686.7s: the line alone on row 10 in
    a cleared full-width window, and row 24 blank -- the same form as the
    losing line, which is why nothing else is on the row here.
    """
    bar = "MOVE VIEW AIM USE QUICK DONE"
    sess = FakeSession([
        (COMBAT, command_bar(bar, "DONE")),
        (DUNGEON, FakeScreen({10: RAN_TEXT})),
        (DUNGEON, FakeScreen({14: STATUS, 24: "MOVE VIEW CAST AREA ENCAMP"})),
    ])
    out = sess.fight(budget=20.0, poll=0.0)
    assert out.outcome == RAN
    assert RAN_TEXT in out.lines


def test_the_three_outcomes_are_told_apart_and_nothing_else_is_claimed():
    """Each line gets its own answer, and an unknown ending is still `ended`.

    The distinction is the whole point of the ticket: before this, a fight
    the party ran away from came back as `ended`, which reads like an
    unremarkable end rather than a party that abandoned five of its six.
    """
    bar = "MOVE VIEW AIM USE QUICK DONE"
    for line, want in ((session.WON_TEXT, session.WON),
                       (session.LOST_TEXT, session.LOST),
                       (RAN_TEXT, RAN),
                       ("THE PARTY WANDERS OFF", session.ENDED)):
        sess = FakeSession([
            (COMBAT, command_bar(bar, "DONE")),
            (DUNGEON, FakeScreen({10: line})),
            (DUNGEON, FakeScreen({14: STATUS,
                                  24: "MOVE VIEW CAST AREA ENCAMP"})),
        ])
        assert sess.fight(budget=20.0, poll=0.0).outcome == want, line


def test_the_fleeing_line_is_the_one_the_game_prints_rather_than_a_guess():
    """`THE PARTY RUNS AWAY`, and the two lines it is chosen between.

    A regression test on a *word*, the same form as the losing one: the
    three are `POST.COM`'s string table entries 2, 3 and 4, all three of them
    on the disks of all three C64 titles, and only the winning one has an
    exclamation mark.
    """
    assert session.RAN_TEXT == "THE PARTY RUNS AWAY"
    assert session.LOST_TEXT == "THE PARTY HAS LOST"
    assert session.WON_TEXT == "THE PARTY HAS WON"
    assert dict(session.OUTCOME_LINES) == {
        session.WON: session.WON_TEXT,
        session.LOST: session.LOST_TEXT,
        session.RAN: session.RAN_TEXT,
    }


def test_a_character_getting_away_is_kept_in_the_log():
    """`GOT AWAY` is evidence a turn did something, and row 24 is where it is.

    `COMBAT`'s own message 5, printed by `$0B07` once `$1719` has written
    `$86`. It was drawn on the command-bar row rather than in the message
    band in both flights at `cited/445`, which is why a fight log that
    only sliced the band would have lost it.
    """
    assert session.RE_NOTABLE.search("GOT AWAY")
    # And the flee prompt itself is an ordinary yes/no bar, which `fight`
    # answers NO: a tactic that means to flee answers it before the loop
    # ever sees it.
    sess = FakeSession([(COMBAT, FakeScreen({24: "FLEE: YES NO"}))])
    assert sess.combat_state().kind == session.BAR_YESNO


# -- the tactic that gets a character to the edge ---------------------------


def arena(x, y, enemy=(26, 13)):
    blocks = synthetic_arena(fighters=((0, x, y), (8, enemy[0], enemy[1])))
    return combat.read_battle(MemoryTarget(blocks))


class Where:
    """A combatant's square, which is all `step_to_edge` reads of one."""

    def __init__(self, x, y, index=0):
        self.x, self.y, self.index = x, y, index


def test_the_walk_reaches_the_edge_of_the_map_and_stops_there():
    """The tactic's whole path, on the arena `automap.combat` reads.

    The real map in the Slums ambush is 56 x 26 with the party at y 12-13, so
    the nearest way out is south and it is twelve squares -- one round for a
    move-12 character and two for a move-9 one. This walks the same case.
    """
    b = arena(25, 13)
    at = Where(25, 13)
    path = [(at.x, at.y)]
    for _ in range(40):
        if fleedrive.edges_of(b.geometry, at):
            break
        key = fleedrive.step_to_edge(b, at)
        assert key is not None, path
        dx, dy = next(d for d, k in session.STEP_KEYS.items() if k == key)
        at = Where(at.x + dx, at.y + dy)
        path.append((at.x, at.y))
    assert path[-1] == (25, b.geometry.height - 1), path
    assert len(path) - 1 == 12, path


def test_the_walk_prefers_a_straight_step_to_a_diagonal_one():
    """Movement is spent by cost, not by squares.

    A diagonal costs two and an orthogonal one -- measured at a live sub-bar,
    `MOVE LEFT` 11 to 9 on `KP_9` and 12 to 11 on `KP_8`
    (`cited/127/sweep1.jsonl`). A tactic that walks diagonally towards a
    straight edge spends twice the movement to get there.
    """
    b = arena(25, 13)
    assert fleedrive.step_to_edge(b, Where(25, 13)) == "KP_2"


def test_a_character_already_on_the_edge_is_told_which_way_is_out():
    b = arena(25, 13)
    w, h = b.geometry.width, b.geometry.height
    assert fleedrive.edges_of(b.geometry, Where(3, 0)) == [(0, -1)]
    assert fleedrive.edges_of(b.geometry, Where(3, h - 1)) == [(0, 1)]
    assert fleedrive.edges_of(b.geometry, Where(0, 5)) == [(-1, 0)]
    assert fleedrive.edges_of(b.geometry, Where(w - 1, 5)) == [(1, 0)]
    assert fleedrive.edges_of(b.geometry, Where(20, 10)) == []


def test_every_way_out_has_a_key_that_takes_it():
    """`OUTWARD` and `STEP_KEYS` must not drift apart: a direction with no key
    would make the tactic walk a character to the edge and stand there."""
    for direction, key in fleedrive.OUTWARD.items():
        assert session.STEP_KEYS[direction] == key


# -- reading the three titles' own POST.COM ---------------------------------


@pytest.mark.parametrize("title", fleedrive.TITLES)
def test_each_title_prints_the_same_line_by_the_same_branch(title):
    """The wording is one reading of three binaries, not one screen.

    Every C64 title's `POST.COM` carries the same 56-entry split pointer
    table with the three outcome lines at entries 2, 3 and 4, and the same
    `CMP #$81 / BNE <the losing arm> / LDX #$02 / LDA #$0A / JSR <print>`.
    The base is derived from the table rather than taken from the PRG header,
    which says `$1000`, `$3000` and `$1220` and is wrong every time.

    Skips with no disks, which is the ordinary state on a machine that has
    only some of the six titles.
    """
    from automap import gamedisks
    root = gamedisks.find(title)
    if root is None:
        pytest.skip(f"no disks for {title}")
    _disk, declared, body = fleedrive.overlay("POST.COM", str(root))
    table = fleedrive.outcome_table(body)
    assert table is not None, title
    base, lo, hi, index = table
    assert base == fleedrive.LINKER_BASE
    assert base != declared                     # the header is never right
    lines = []
    for n in range(index, index + 3):
        at = body[lo + n] | body[hi + n] << 8
        lines.append(body[at - base:body.index(b"\x00", at - base)].decode())
    assert lines == ["THE PARTY RUNS AWAY", "THE PARTY HAS LOST",
                     "THE PARTY HAS WON !"]
    branch = fleedrive.flee_branch(body)
    assert branch is not None, title
    _at, message, row = branch
    assert (message, row) == (index, 10)


# -- stepping off only from a square no enemy stands beside ------------------


def edge_walk(b, at, **kwargs):
    """Walk to the edge, then along it for as long as the walk goes on."""
    path = [(at.x, at.y)]
    for _ in range(80):
        key = fleedrive.step_to_edge(b, at, **kwargs)
        if key is None:
            return at, path
        dx, dy = next(d for d, k in session.STEP_KEYS.items() if k == key)
        at = Where(at.x + dx, at.y + dy)
        path.append((at.x, at.y))
    raise AssertionError(path)


def test_a_safe_walk_ends_on_an_edge_square_no_enemy_stands_beside():
    height = arena(25, 13).geometry.height
    b = arena(25, 13, enemy=(24, height - 1))
    end, _ = edge_walk(b, Where(25, 13), safe=True)
    assert fleedrive.edges_of(b.geometry, end)
    assert fleedrive.adjacent_enemies(b, end.x, end.y) == []
    plain, _ = edge_walk(b, Where(25, 13))
    assert fleedrive.adjacent_enemies(b, plain.x, plain.y) != []


def test_with_no_safe_edge_the_walk_falls_back_to_the_nearest_edge(
        monkeypatch):
    b = arena(25, 13)
    monkeypatch.setattr(fleedrive, "adjacent_enemies",
                        lambda battle, x, y: [object()])
    end, path = edge_walk(b, Where(25, 13), safe=True)
    assert (end.x, end.y) == (25, b.geometry.height - 1), path
    assert len(path) - 1 == 12


class _Fighter:
    def __init__(self, x, y, movement, alive=True, on_map=True):
        self.x, self.y, self.movement = x, y, movement
        self.alive, self.on_map = alive, on_map


class _Field:
    def __init__(self, *enemies):
        self.enemies = enemies


def test_may_step_off_only_with_nobody_beside_or_when_faster():
    me = _Fighter(5, 0, 12)
    assert fleedrive.may_step_off(_Field(_Fighter(9, 9, 12)), me)
    assert fleedrive.may_step_off(_Field(_Fighter(5, 1, 9)), me)
    assert not fleedrive.may_step_off(_Field(_Fighter(5, 1, 12)), me)
    assert not fleedrive.may_step_off(_Field(_Fighter(5, 1, None)), me)
    assert not fleedrive.may_step_off(_Field(_Fighter(5, 1, 9),
                                             _Fighter(6, 1, 12)), me)
    assert fleedrive.may_step_off(_Field(_Fighter(5, 1, 12, alive=False)), me)


def test_may_step_off_compares_with_the_fastest_enemy_anywhere_on_the_map():
    """`COMBAT $1768` keeps the fastest of each side over every combatant in
    the fight, and `$16FA` compares the leaver with that, not with the
    enemies beside him: a move-9 member beside a move-6 kobold, with a
    move-12 enemy across the map, is a slower leaver and fails."""
    me = _Fighter(5, 0, 9)
    assert not fleedrive.may_step_off(
        _Field(_Fighter(5, 1, 6), _Fighter(15, 9, 12)), me)
    assert fleedrive.may_step_off(
        _Field(_Fighter(5, 1, 6), _Fighter(15, 9, 12, alive=False)), me)
    assert fleedrive.may_step_off(
        _Field(_Fighter(5, 1, 6), _Fighter(15, 9, 12, on_map=False)), me)


def test_the_default_walk_is_unchanged():
    b = arena(25, 13)
    path = []
    at = Where(25, 13)
    while not fleedrive.edges_of(b.geometry, at):
        key = fleedrive.step_to_edge(b, at, safe=False)
        dx, dy = next(d for d, k in session.STEP_KEYS.items() if k == key)
        at = Where(at.x + dx, at.y + dy)
        path.append((at.x, at.y))
    height = b.geometry.height
    assert path == [(25, y) for y in range(14, height)]
    assert len(path) == 12
