"""Map geometry: turn a `Geo` into drawing primitives.

No Qt in here. The window paints these, the tests assert on them, and `to_svg`
renders them offline so a map can be eyeballed against a fan map without
launching anything.

**Doors are drawn as doors.** On a hand-drawn dungeon map a door is not a
differently-coloured wall -- it is a break in the wall with a door leaf set into
the gap. That is what `edge_primitives` emits, and it is the whole reason this
module exists rather than the drawing being inlined into the window.

**Every edge is drawn from both sides.** `Geo.to_text` draws only each square's
north and west edges and lets reciprocity supply the rest, but wall art is only
0.960 reciprocal across the corpus -- so one-way edges exist, and that approach
silently drops them. Here an edge is drawn if *either* side has art, and takes
whichever side's barrier is easier to get through.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from por.geo import (
    DIRECTIONS,
    EAST,
    GRID,
    LOCKED,
    NORTH,
    OPPOSITE,
    PASSABLE,
    SOLID,
    SOUTH,
    STEP,
    WEST,
    WIZARD_LOCKED,
    Geo,
)

from . import icons

CELL = 34
MARGIN = 26

# Fractions of a cell.
DOOR_GAP = 0.52          # how much of the wall the doorway removes
DOOR_LEAF = 0.44         # the leaf drawn in the gap, along the wall
DOOR_THICK = 0.17        # and across it
BAR = 0.30               # the locked-door bar, across the wall
STAR = 0.15              # wizard-lock mark

# How hard an edge is to cross. Used to merge the two sides of one edge: the
# easier reading wins, so a door seen from one side is a door from both.
_RANK = {PASSABLE: 0, LOCKED: 1, WIZARD_LOCKED: 2, SOLID: 3}


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    kind: str = "wall"


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    kind: str = "door"


#: Solid rock, in the shades a painter inks it. The old fill was `#e7ecf2`,
#: the same tint a roofed square carries on the area map, which against paper
#: reads as more paper. Stated here because the hatching is geometry's business
#: and the two halves have to agree: the fill is the ground the pen crosses.
ROCK_FILL = "#c3d0dd"
ROCK_HATCH = "#68809a"    # the hatching pen: ink thinned, never the wall ink

#: Hatch lines per cell, and the closest they may come in pixels measured
#: **across** the lines. Below the floor the pattern fills in and the square is
#: drawn as a plain fill instead, which is honest about what it has become.
#: Cross-hatching lays down two sets and so is spaced wider: at the single
#: pattern's spacing it stops reading as strokes and becomes a grey.
HATCH_STEPS = 3
CROSS_STEPS = 2
HATCH_MIN = 4.0


@dataclass(frozen=True)
class Hatch(Rect):
    """A square of solid rock: a fill, with pen strokes laid over it.

    **A `Hatch` is a `Rect`**, so a painter that has never heard of hatching
    still fills the square and loses only the strokes. That is the whole reason
    for the subclass -- the two painters can learn about it separately.

    `lines` are absolute `(x1, y1, x2, y2)`, already clipped to the square, so
    no painter needs a clip region. Empty when the cell is too small to carry
    them; see `hatch_lines`.
    """

    lines: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class Poly:
    points: tuple[tuple[float, float], ...]
    kind: str = "party"


@dataclass(frozen=True)
class Label:
    """A short piece of text at a point.

    The combat view puts hit points in a square with it, where `(x, y)` is the
    centre. A `note-count` puts the number of notes on a square beside its
    marker, where `(x, y)` is the **bottom right** of the text -- the marker is
    already against the cell's right edge and the count grows leftwards from it.
    """

    x: float
    y: float
    text: str
    kind: str = "hp"


@dataclass(frozen=True)
class Glyph:
    """One icon from `automap.icons`, filled into a square box.

    `(x, y)` is the box's top-left corner and `size` its side, because that is
    what both painters want: `QPainter` translates and scales, and SVG writes
    the same as a `transform`. No font metrics anywhere -- see `icons.py` for
    why the icons are paths and not a bundled font.
    """

    x: float
    y: float
    size: float
    name: str
    kind: str = "note"


@dataclass(frozen=True)
class Edge:
    """One wall segment, after merging both squares' views of it."""

    x: int
    y: int
    direction: int
    art: int
    barrier: int

    @property
    def is_door(self) -> bool:
        return self.barrier != SOLID


def merged_edge(geo: Geo, x: int, y: int, direction: int) -> Edge | None:
    """This square's edge, unioned with the neighbour's view of the same edge.

    Returns None when neither side draws a wall there.
    """
    art = geo.wall(x, y, direction)
    barrier = geo.barrier(x, y, direction)
    dx, dy = STEP[direction]
    nx, ny = x + dx, y + dy
    if 0 <= nx < GRID and 0 <= ny < GRID:
        back = OPPOSITE[direction]
        other_art = geo.wall(nx, ny, back)
        if other_art and (not art or _RANK[geo.barrier(nx, ny, back)] < _RANK[barrier]):
            barrier = geo.barrier(nx, ny, back)
        art = max(art, other_art)
    if not art:
        return None
    return Edge(x, y, direction, art, barrier)


def _endpoints(x: int, y: int, direction: int, cell: int, margin: int):
    left = margin + x * cell
    top = margin + y * cell
    right, bottom = left + cell, top + cell
    if direction == NORTH:
        return (left, top), (right, top)
    if direction == SOUTH:
        return (left, bottom), (right, bottom)
    if direction == WEST:
        return (left, top), (left, bottom)
    return (right, top), (right, bottom)


def edge_primitives(edge: Edge, cell: int = CELL, margin: int = MARGIN):
    """A wall, or a wall broken by a door.

    A solid edge is one line. A door is two stubs with a leaf between them,
    plus a bar if it is locked and a star if it is wizard-locked.
    """
    (x1, y1), (x2, y2) = _endpoints(edge.x, edge.y, edge.direction, cell, margin)
    if not edge.is_door:
        yield Line(x1, y1, x2, y2, "wall")
        return

    horizontal = y1 == y2
    mid = ((x1 + x2) / 2, (y1 + y2) / 2)
    half_gap = cell * DOOR_GAP / 2

    if horizontal:
        yield Line(x1, y1, mid[0] - half_gap, y1, "wall")
        yield Line(mid[0] + half_gap, y1, x2, y2, "wall")
        w, h = cell * DOOR_LEAF, cell * DOOR_THICK
    else:
        yield Line(x1, y1, x1, mid[1] - half_gap, "wall")
        yield Line(x2, mid[1] + half_gap, x2, y2, "wall")
        w, h = cell * DOOR_THICK, cell * DOOR_LEAF

    kind = {PASSABLE: "door", LOCKED: "door-locked",
            WIZARD_LOCKED: "door-wizard"}[edge.barrier]
    yield Rect(mid[0] - w / 2, mid[1] - h / 2, w, h, kind)

    if edge.barrier in (LOCKED, WIZARD_LOCKED):
        b = cell * BAR / 2
        if horizontal:
            yield Line(mid[0], mid[1] - b, mid[0], mid[1] + b, "bar")
        else:
            yield Line(mid[0] - b, mid[1], mid[0] + b, mid[1], "bar")

    if edge.barrier == WIZARD_LOCKED:
        s = cell * STAR
        cx, cy = mid[0] + (0 if horizontal else s * 1.9), mid[1] - s * 1.9
        yield Line(cx - s, cy, cx + s, cy, "star")
        yield Line(cx, cy - s, cx, cy + s, "star")


def party_marker(x: int, y: int, facing: int, cell: int = CELL,
                 margin: int = MARGIN) -> Poly:
    """A triangle pointing the way the party is looking."""
    cx = margin + x * cell + cell / 2
    cy = margin + y * cell + cell / 2
    r = cell * 0.28
    nose = {NORTH: (0, -r), EAST: (r, 0), SOUTH: (0, r), WEST: (-r, 0)}[facing]
    back = {NORTH: ((-r * .8, r * .6), (r * .8, r * .6)),
            EAST: ((-r * .6, -r * .8), (-r * .6, r * .8)),
            SOUTH: ((-r * .8, -r * .6), (r * .8, -r * .6)),
            WEST: ((r * .6, -r * .8), (r * .6, r * .8))}[facing]
    pts = ((cx + nose[0], cy + nose[1]),
           (cx + back[0][0], cy + back[0][1]),
           (cx + back[1][0], cy + back[1][1]))
    return Poly(pts, "party")


# Notes sit in the square's top-right corner, clear of the party marker in the
# middle and of every wall. `NOTE_INSET` is measured against the 3px wall
# stroke: half of that stroke lies inside the cell, so anything at 2 or more
# never touches one. See `test_a_note_never_lands_on_a_wall`.
NOTE_SIZE = 13
NOTE_INSET = 3
COUNT_SIZE = 9


def note_primitives(notes, cell: int = CELL, margin: int = MARGIN):
    """The marker for every square that carries notes.

    **Drawn whatever the fog says.** A note is something you know; hiding it
    because the square is currently fogged would be perverse.

    A square with several notes draws the first one's icon and a count, rather
    than trying to fit four icons into a 34px cell.
    """
    for (x, y), items in sorted(notes.items()):
        if not items:
            continue
        left = margin + x * cell + cell - NOTE_INSET - NOTE_SIZE
        top = margin + y * cell + NOTE_INSET
        yield Glyph(left, top, NOTE_SIZE, items[0].icon, "note")
        if len(items) > 1:
            yield Label(left + NOTE_SIZE, top + NOTE_SIZE + COUNT_SIZE - 2,
                        str(len(items)), "note-count")


def map_primitives(geo: Geo, visible=None, cell: int = CELL,
                   margin: int = MARGIN):
    """Every primitive for one map.

    `visible(x, y) -> bool` filters to explored squares; pass None for all of
    them. An edge is drawn when either of its squares is visible, so the wall
    you are standing against is drawn even before you have been to the far side.
    """
    def shown(x, y):
        return visible is None or visible(x, y)

    for y in range(GRID):
        for x in range(GRID):
            if shown(x, y) and geo.is_indoor(x, y):
                yield Rect(margin + x * cell, margin + y * cell, cell, cell,
                           "roofed")

    seen: set[tuple[int, int, int]] = set()
    for y in range(GRID):
        for x in range(GRID):
            for d in DIRECTIONS:
                dx, dy = STEP[d]
                nx, ny = x + dx, y + dy
                key = tuple(sorted([(x, y, d), (nx, ny, OPPOSITE[d])]))[0]
                if key in seen:
                    continue
                seen.add(key)
                if not (shown(x, y) or shown(nx, ny)):
                    continue
                edge = merged_edge(geo, x, y, d)
                if edge:
                    yield from edge_primitives(edge, cell, margin)


# -- solid rock --------------------------------------------------------------

def hatch_lines(x: float, y: float, w: float, h: float,
                steps: int | None = None, cross: bool = False,
                least: float = HATCH_MIN):
    """Parallel 45-degree strokes across one square, clipped to its own edges.

    **Anchored at `(x, y)`**, the square's own top-left, so the pattern cannot
    crawl when the camera moves it -- a pattern anchored to the canvas keeps its
    origin while the square slides over it, and every stroke walks a pixel a
    step. The spacing divides the cell exactly, so neighbouring squares still
    join up into one run of hatching across a mass of rock.

    Returns `()` when the strokes would come closer than `least` pixels: at that
    point they merge, and a plain fill says the same thing without pretending.
    """
    step = min(w, h) / (steps or (CROSS_STEPS if cross else HATCH_STEPS))
    if step / math.sqrt(2) < least:
        return ()
    out = []
    for down in (True, False) if cross else (True,):
        # Offsets are multiples of the spacing measured from the corner, over
        # the range where a 45-degree line still crosses the square at all.
        for k in range(-int(h // step), int(w // step) + 1):
            off = k * step
            t0, t1 = max(0.0, -off / h), min(1.0, (w - off) / h)
            if t1 - t0 < 1e-9:
                continue
            xa, xb = off + t0 * h, off + t1 * h
            ya, yb = (t0 * h, t1 * h) if down else (h - t0 * h, h - t1 * h)
            out.append((x + xa, y + ya, x + xb, y + yb))
    return tuple(out)


SVG_STYLE = {
    "roofed": 'fill="#e7ecf2" stroke="none"',
    # Solid rock on the combat map: fill, pen, and the heavy line Dyson Logos
    # draws around a mass of it.
    "block": f'fill="{ROCK_FILL}" stroke="none"',
    "hatch": f'stroke="{ROCK_HATCH}" stroke-width="1"',
    "rock-edge": 'stroke="#16202b" stroke-width="2.5" stroke-linecap="round"',
    "wall": 'stroke="#16202b" stroke-width="3" stroke-linecap="square"',
    "bar": 'stroke="#16202b" stroke-width="2"',
    "star": 'stroke="#9e2b9e" stroke-width="1.6"',
    "door": 'fill="#ffffff" stroke="#16202b" stroke-width="2"',
    "door-locked": 'fill="#ffffff" stroke="#16202b" stroke-width="2"',
    "door-wizard": 'fill="#ffffff" stroke="#9e2b9e" stroke-width="2"',
    "party": 'fill="#0067c7" stroke="none"',
    "note": 'fill="#b8601f" stroke="none"',
    "note-count": 'fill="#b8601f" font-family="sans-serif" font-size="9" '
                  'text-anchor="end"',
}


def to_svg(geo: Geo, visible=None, party=None, cell: int = CELL,
           margin: int = MARGIN, notes=None) -> str:
    """Render one map to standalone SVG, for checking it by eye.

    `notes` is the state's square-to-notes mapping; pass it and the markers
    come out too, because they are the same primitives the window paints.
    """
    size = GRID * cell + margin * 2
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" '
           f'height="{size}" viewBox="0 0 {size} {size}">',
           f'<rect width="{size}" height="{size}" fill="#fbfcfd"/>']
    for i in range(GRID + 1):
        p = margin + i * cell
        out.append(f'<line x1="{p}" y1="{margin}" x2="{p}" '
                   f'y2="{margin + GRID * cell}" stroke="#dbe3ec"/>')
        out.append(f'<line x1="{margin}" y1="{p}" x2="{margin + GRID * cell}" '
                   f'y2="{p}" stroke="#dbe3ec"/>')

    prims = list(map_primitives(geo, visible, cell, margin))
    if party:
        prims.append(party_marker(*party, cell, margin))
    if notes:
        prims.extend(note_primitives(notes, cell, margin))
    for p in prims:
        style = SVG_STYLE.get(p.kind, "")
        if isinstance(p, Hatch):
            out.append(f'<rect x="{p.x}" y="{p.y}" width="{p.w}" '
                       f'height="{p.h}" {style}/>')
            for x1, y1, x2, y2 in p.lines:
                out.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" '
                           f'y2="{y2:.2f}" {SVG_STYLE["hatch"]}/>')
        elif isinstance(p, Line):
            out.append(f'<line x1="{p.x1}" y1="{p.y1}" x2="{p.x2}" '
                       f'y2="{p.y2}" {style}/>')
        elif isinstance(p, Rect):
            out.append(f'<rect x="{p.x}" y="{p.y}" width="{p.w}" '
                       f'height="{p.h}" {style}/>')
        elif isinstance(p, Glyph):
            scale = p.size / icons.BOX
            out.append(f'<path transform="translate({p.x},{p.y}) '
                       f'scale({scale:.5f})" d="{icons.path_data(p.name)}" '
                       f'{style}/>')
        elif isinstance(p, Label):
            out.append(f'<text x="{p.x}" y="{p.y}" {style}>{p.text}</text>')
        else:
            pts = " ".join(f"{a},{b}" for a, b in p.points)
            out.append(f'<polygon points="{pts}" {style}/>')
    out.append("</svg>")
    return "\n".join(out)
