from __future__ import annotations

"""How solid rock is shaded on the combat map.

Three options, chosen by `combat.SHADING`: a plain darker fill, one set of
45-degree strokes, or two. The plan is `docs/111-map-shading.md`; what is
tested here is everything the plan said to watch -- that the pattern is
anchored to the square rather than the canvas, that it survives the cell
shrinking, and that a crowded fight still reads.
"""


import dataclasses

import pytest
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


# --- and what the canvas paints ---------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def drawn(cell=None):
    """The combat canvas, painted offscreen. Returns the image and the canvas.

    Colours are counted rather than compared to a reference image: the pen is
    antialiased along a 45-degree stroke, so almost no pixel lands on the pen's
    exact value and only "darker than the fill" is a stable question.
    """
    from automap.window import CombatCanvas

    canvas = CombatCanvas()
    canvas.show_battle(battle())
    if cell is not None:
        canvas.cell = cell
        canvas._resize()
    # `sizeHint`, not `minimumSize`: the minimum is the floor the canvas will
    # shrink to when the window is small, and this wants the cell it asked for.
    canvas.resize(canvas.sizeHint())
    return canvas.grab().toImage(), canvas


def inside_the_rock(image, canvas, inset: int = 3):
    """Every pixel well inside the rock mass, clear of its inked boundary."""
    x0, y0, _, _ = canvas.box
    cell = canvas.cell
    left = combat.MARGIN + (min(ROCK[0]) - x0) * cell + inset
    top = combat.MARGIN + (min(ROCK[1]) - y0) * cell + inset
    # Stop at the camera rectangle: it is dashed over the rock in this arena,
    # and its blue is neither the fill nor a stroke.
    right = combat.MARGIN + (min(canvas.battle.camera[0],
                                 max(ROCK[0]) + 1) - x0) * cell - inset
    bottom = combat.MARGIN + (max(ROCK[1]) + 1 - y0) * cell - inset
    return [image.pixelColor(x, y)
            for y in range(top, bottom) for x in range(left, right)]


def test_the_canvas_paints_the_strokes_over_the_fill(app):
    """The branch the geometry was waiting for: `Hatch` before `Rect`, because
    a `Hatch` *is* a `Rect` and the older branch would swallow it."""
    from automap import window as win

    image, canvas = drawn()
    pixels = inside_the_rock(image, canvas)
    fill = win.BLOCK.lightnessF()
    assert sum(1 for c in pixels if c.name() == win.BLOCK.name()) > 100
    assert sum(1 for c in pixels if c.lightnessF() < fill - 0.02) > 100


def test_a_small_cell_degrades_to_a_plain_fill(app):
    """Below the stroke floor `hatch_lines` yields nothing, and the square is
    the fill alone -- which is honest about what it has become."""
    from automap import window as win

    image, canvas = drawn(cell=combat.CELL_MIN)
    pixels = inside_the_rock(image, canvas)
    fill = win.BLOCK.lightnessF()
    assert pixels and all(c.name() == win.BLOCK.name() for c in pixels)
    assert not any(c.lightnessF() < fill - 0.02 for c in pixels)


def test_the_boundary_is_inked_even_when_the_strokes_are_gone(app):
    """`Line` was ignored by this canvas: without it a mass of rock at the
    smallest cell is a flat tint with no edge at all."""
    from automap import window as win

    for cell in (combat.CELL_MAX, combat.CELL_MIN):
        image, canvas = drawn(cell=cell)
        x0, y0, _, _ = canvas.box
        # A point on the rock's left edge, midway down it.
        x = combat.MARGIN + (min(ROCK[0]) - x0) * cell
        y = combat.MARGIN + (min(ROCK[1]) - y0) * cell + 2 * cell
        edge = [image.pixelColor(x + dx, y).lightnessF() for dx in (-1, 0, 1)]
        assert min(edge) < win.INK.lightnessF() + 0.25


def test_the_fill_is_a_step_off_the_paper_rather_than_the_roof_tint():
    """`#e7ecf2` was the tint a roofed square carries on the area map, which
    against `#fbfcfd` paper reads as more paper."""
    from automap import window as win

    assert (win.BLOCK.name(), win.HATCH_PEN.name()) == ("#c3d0dd", "#68809a")
    assert win.BLOCK.name() != win.ROOF.name()
