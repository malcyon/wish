"""How solid rock is shaded on the combat map.

Three options, chosen by `combat.SHADING`: a plain darker fill, one set of
45-degree strokes, or two. The plan is `docs/111-map-shading.md`; what is
tested here is everything the plan said to watch -- that the pattern is
anchored to the square rather than the canvas, that it survives the cell
shrinking, and that a crowded fight still reads.
"""

from __future__ import annotations

import dataclasses

from gamedata import synthetic_arena

from automap import combat
from automap.render import Hatch, Line, Rect, hatch_lines
from automap.target import MemoryTarget

# The arena's rock, from `tests/gamedata.py`: x 20-22, y 11-15.
ROCK = (range(20, 23), range(11, 16))


def battle():
    return combat.read_battle(MemoryTarget(synthetic_arena()))


def kinds(prims):
    return [p.kind for p in prims]


# --- the pattern ------------------------------------------------------------

def test_the_strokes_stay_inside_the_square():
    """Clipped by the geometry, so no painter needs a clip region."""
    lines = hatch_lines(10, 20, 30, 30)
    assert lines
    for x1, y1, x2, y2 in lines:
        assert 10 <= x1 <= 40 and 10 <= x2 <= 40
        assert 20 <= y1 <= 50 and 20 <= y2 <= 50
        assert abs(abs(x2 - x1) - abs(y2 - y1)) < 1e-6      # 45 degrees


def test_the_pattern_is_anchored_to_the_square_and_does_not_crawl():
    """A pattern anchored to the canvas keeps its origin while the square
    slides over it, so every stroke walks as the camera scrolls."""
    here = hatch_lines(0, 0, 30, 30)
    there = hatch_lines(137, 91, 30, 30)
    assert [(x1 - 137, y1 - 91, x2 - 137, y2 - 91)
            for x1, y1, x2, y2 in there] == list(here)


def test_neighbouring_squares_join_up():
    """The spacing divides the cell, so a mass of rock is one run of hatching
    and not a grid of tiles each with its own pattern."""
    def crossings(lines):
        # Where the strokes meet the shared edge, corners aside: a stroke that
        # only touches a corner has nothing to continue into.
        return sorted(y for x1, y1, x2, y2 in lines
                      for x, y in ((x1, y1), (x2, y2))
                      if abs(x - 30) < 1e-6 and 0 < y < 30)

    left = crossings(hatch_lines(0, 0, 30, 30))
    assert left and left == crossings(hatch_lines(30, 0, 30, 30))


def test_cross_hatching_is_two_sets_at_opposite_slopes():
    slopes = {round((y2 - y1) / (x2 - x1)) for x1, y1, x2, y2
              in hatch_lines(0, 0, 30, 30, cross=True)}
    assert slopes == {1, -1}
    assert {round((y2 - y1) / (x2 - x1))
            for x1, y1, x2, y2 in hatch_lines(0, 0, 30, 30)} == {1}


def test_a_cell_too_small_for_the_spacing_falls_back_to_a_plain_fill():
    """Absolute spacing goes solid as the window shrinks the cell. Below the
    floor there are no strokes at all, and the fill says the same thing."""
    assert hatch_lines(0, 0, 30, 30)
    assert hatch_lines(0, 0, 12, 12) == ()
    assert hatch_lines(0, 0, 12, 12, cross=True)          # wider spaced, still on
    assert hatch_lines(0, 0, 6, 6, cross=True) == ()


# --- what the battlefield yields --------------------------------------------

def test_a_hatch_is_a_rect_so_an_older_painter_still_fills_the_square():
    """The degradation that matters: a painter that has not learned about
    hatching loses the strokes, not the rock."""
    hatched = next(p for p in combat.battlefield(battle(), shading=combat.HATCH)
                   if p.kind == "block")
    assert isinstance(hatched, Hatch) and isinstance(hatched, Rect)
    assert (hatched.w, hatched.h) == (hatched.h, hatched.w)


def test_the_plain_fill_is_the_old_primitive_and_nothing_else():
    prims = list(combat.battlefield(battle(), shading=combat.FILL))
    rock = [p for p in prims if p.kind == "block"]
    assert rock and not any(isinstance(p, Hatch) for p in rock)
    assert "rock-edge" not in kinds(prims)


def test_every_rock_square_is_shaded_and_no_other_square_is():
    b = battle()
    box = combat.extent(b)
    cell = combat.cell_for(box[2])
    hatched = {((p.x - combat.MARGIN) // cell + box[0],
                (p.y - combat.MARGIN) // cell + box[1])
               for p in combat.battlefield(b, box, cell, shading=combat.CROSS)
               if isinstance(p, Hatch)}
    assert hatched == {(x, y) for x in ROCK[0] for y in ROCK[1]}


def test_the_heavy_line_runs_where_rock_meets_ground_only():
    """Dyson Logos's rock is one inked shape with a hatched interior, not a
    tiling: the boundary is drawn, the joins between rock squares are not."""
    b = battle()
    box = combat.extent(b)
    cell = combat.cell_for(box[2])
    edges = [p for p in combat.battlefield(b, box, cell, shading=combat.HATCH)
             if isinstance(p, Line) and p.kind == "rock-edge"]
    # A 3 x 5 block: six squares' worth of edge along the sides, three along
    # the top and three along the bottom, and nothing inside.
    assert len(edges) == 2 * 5 + 2 * 3
    lengths = {round(max(abs(p.x2 - p.x1), abs(p.y2 - p.y1))) for p in edges}
    assert lengths == {cell}


def test_the_fills_are_all_laid_down_before_the_outline():
    """A stroke sits astride the line it is drawn on, so a fill emitted after
    one would paint over half of it."""
    order = kinds(combat.battlefield(battle(), shading=combat.CROSS))
    assert order.index("rock-edge") > max(
        n for n, k in enumerate(order) if k == "block")


def test_a_crowded_fight_still_puts_every_combatant_over_the_hatching():
    """Party green and enemy red sit on top of the pattern; hatching that is
    too dense turns the map into texture and the squares stop reading."""
    fighters = [(0, 21, 13)] + [(8 + n, 19 + n % 6, 10 + n // 6)
                                for n in range(12)]
    b = combat.read_battle(MemoryTarget(synthetic_arena(fighters=fighters)))
    assert len(b.combatants) == 13
    prims = list(combat.battlefield(b, shading=combat.CROSS))
    last_rock = max(n for n, p in enumerate(prims)
                    if p.kind in ("block", "rock-edge"))
    people = [n for n, p in enumerate(prims)
              if p.kind in ("party", "enemy", "ready")]
    assert people and min(people) > last_rock
    # ...and one square each, whatever is under them.
    fills = [p for p in prims if p.kind in ("party", "enemy")]
    assert len(fills) == 13 and all(isinstance(p, Rect)
                                    and not isinstance(p, Hatch) for p in fills)


def test_the_smallest_cell_the_view_uses_degrades_rather_than_going_solid():
    """`cell_for` bottoms out at CELL_MIN; at that size a single hatch is a
    plain fill and the cross is still just distinguishable."""
    b = battle()
    box = combat.extent(b)
    plain = [p for p in combat.battlefield(b, box, combat.CELL_MIN,
                                           shading=combat.HATCH)
             if isinstance(p, Hatch)]
    assert plain and all(p.lines == () for p in plain)
    big = [p for p in combat.battlefield(b, box, combat.CELL_MAX,
                                         shading=combat.HATCH)
           if isinstance(p, Hatch)]
    assert all(p.lines for p in big)


def test_shading_is_one_constant():
    """The whole choice, so switching it is a one-word edit."""
    assert combat.SHADING in (combat.FILL, combat.HATCH, combat.CROSS)
    assert kinds(combat.battlefield(battle())) == kinds(
        combat.battlefield(battle(), shading=combat.SHADING))


def test_a_dimmed_combatant_still_reads_against_the_pattern():
    """Dead is drawn faint, and faint over hatching is the case that could
    disappear: it keeps its outline and its number."""
    b = battle()
    dead = dataclasses.replace(b.combatants[-1], hp=0)
    b = dataclasses.replace(b, combatants=b.combatants[:-1] + (dead,))
    assert "enemy-dim" in kinds(combat.battlefield(b, shading=combat.CROSS))
