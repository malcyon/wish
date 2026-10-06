"""Curse's world map for the automapper tab: read off the disks, laid out.

No Qt here. `load_route_map` reads the two world-map scripts and the display
driver off a title's C64 disks, or the scripts and marker cells off its Amiga
disks, through `goldbox.curse_worldmap`; `place_points`
puts each place at its marker cell, scaled to a rectangle; `display_name` is
the name as the tab writes it. `automap.window.RouteCanvas` paints the result.
"""

from __future__ import annotations

import glob
import logging
import os

from goldbox.curse_worldmap import (
    Road,
    WorldMap,
    read_amiga_marker_cells,
    read_world_map,
)
from goldbox.d64 import D64, split_load_address

from .c64 import machine_for
from .maps import amiga_images
from .paths import disk_globs

_log = logging.getLogger("wish.automap.routes")

#: The display driver whose marker tables give each place's cell.
DRIVER = "GDRIVE02"


def script_names(game) -> tuple[str, ...]:
    """The world-map scripts of a title, `ECL50` style, or none."""
    return tuple(f"ECL{area:02X}"
                 for area in machine_for(game).title.world_map_areas)


def _read_files(disks, game, names) -> dict[str, bytes]:
    """Each named file, without its load address, from the first disk of the
    title that carries it and reads cleanly. A missing file is simply absent."""
    paths: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in glob.glob(os.path.join(str(disks), pattern)):
            paths.setdefault(os.path.normcase(os.path.abspath(path)), path)
    found: dict[str, bytes] = {}
    for path in sorted(paths.values()):
        try:
            image = D64.open(path)
        except Exception:                      # not a disk, or not readable
            continue
        for name in names:
            if name in found:
                continue
            try:
                entry = image.find(name.encode())
                if entry is not None:
                    found[name] = split_load_address(image.read_file(entry))[1]
            except Exception:                  # a broken chain is no candidate
                continue
    return found


#: The Amiga disks' files: the program holds the marker cells, and the script
#: library holds each world-map script as a block.
AMIGA_PROGRAM = "/CURSE"
AMIGA_SCRIPTS = "/DISKB/ECL.GLB"


def _read_amiga(disks, game, names) -> tuple[dict[str, bytes], tuple] | None:
    """The scripts, named `ECL50` style, and the marker cells off the title's
    Amiga disks, or None when no disk carries the program and the scripts."""
    from goldbox.amiga_adf import AmigaDisk
    from goldbox.amiga_savegame import area_script
    program = library = None
    for image in amiga_images(disks, machine_for(game).title):
        try:
            disk = AmigaDisk.open(str(image))
            for path, _entry in disk.walk():
                if path.upper() == AMIGA_PROGRAM and program is None:
                    program = disk.read_file(path)
                elif path.upper() == AMIGA_SCRIPTS and library is None:
                    library = disk.read_file(path)
        except Exception as err:               # not readable: no candidate
            _log.debug("Amiga disk %s not read: %s", image, err)
            continue
    if program is None or library is None:
        return None
    scripts = {n: area_script(library, int(n[3:], 16)) for n in names}
    return scripts, read_amiga_marker_cells(program)


def load_route_map(disks, game) -> WorldMap | None:
    """The title's places, roads and marker cells, or None.

    None for a title with no world map, a missing folder, disks that do not
    carry the scripts and the driver, and anything the reader blocks; the
    reason goes to the debug log. Every place must have a cell, since a place
    with nowhere to stand cannot be drawn.
    """
    if game is None or disks is None:
        return None
    try:
        names = script_names(game)
        if not names:
            return None
        files = _read_files(disks, game, names + (DRIVER,))
        missing = [n for n in names + (DRIVER,) if n not in files]
        if not missing:
            world = read_world_map({n: files[n] for n in names}, files[DRIVER])
        else:
            amiga = _read_amiga(disks, game, names)
            if amiga is None:
                _log.debug("World map not drawn: %s not found on the disks",
                           ", ".join(missing))
                return None
            world = read_world_map(amiga[0], cells=amiga[1])
    except Exception as err:                   # untrusted bytes: stay blank
        _log.debug("World map not drawn: %s", err, exc_info=True)
        return None
    if not world.places or any(p.cell is None for p in world.places):
        _log.debug("World map not drawn: a place has no marker cell")
        return None
    return world


def display_name(name: str | None) -> str:
    """A place as the tab writes it: the game prints capitals, the tab
    capitalises each word. Empty for a place no script names."""
    return name.title() if name else ""


def travel_direction(road: Road) -> tuple[int, int] | None:
    """The place a one-way road leaves and the place it reaches, or None where
    the road runs both ways or has no leg at all."""
    if road.forward is not None and road.backward is None:
        return road.a, road.b
    if road.backward is not None and road.forward is None:
        return road.b, road.a
    return None


def is_conditional(road: Road) -> bool:
    """Is the road offered only in some of the menus that list it, in either
    direction?"""
    return any(leg is not None and leg.conditional
               for leg in (road.forward, road.backward))


#: An arrowhead's length along its road and half its width across, in pixels.
ARROW_LENGTH = 17.0
ARROW_HALF_WIDTH = 7.5

Point = tuple[float, float]


def arrowhead(src: Point, dst: Point, length: float = ARROW_LENGTH,
              half_width: float = ARROW_HALF_WIDTH) -> tuple[Point, ...]:
    """The corners of a head pointing from `src` towards `dst`, centred on the
    midpoint of the two: the tip first, then the two corners of its base. Empty
    for two places at the same point."""
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    run = (dx * dx + dy * dy) ** 0.5
    if run == 0:
        return ()
    ux, uy = dx / run, dy / run
    mx, my = (src[0] + dst[0]) / 2, (src[1] + dst[1]) / 2
    bx, by = mx - ux * length / 2, my - uy * length / 2
    return ((mx + ux * length / 2, my + uy * length / 2),
            (bx - uy * half_width, by + ux * half_width),
            (bx + uy * half_width, by - ux * half_width))


def place_points(world: WorldMap, left: float, top: float,
                 width: float, height: float) -> dict[int, tuple[float, float]]:
    """Where each place sits in this rectangle, by place index.

    The marker cells keep their proportions: one scale in both directions,
    chosen so the farthest cells touch the rectangle's edges, and the whole
    centred in it. A rectangle with no room puts every place at its middle.
    """
    cells = {p.index: p.cell for p in world.places if p.cell is not None}
    if not cells:
        return {}
    columns = [c for c, _ in cells.values()]
    rows = [r for _, r in cells.values()]
    across = max(columns) - min(columns)
    down = max(rows) - min(rows)
    fits = ([width / across] if across else []) + ([height / down] if down else [])
    scale = max(min(fits), 0.0) if fits else 0.0
    x0 = left + (width - across * scale) / 2
    y0 = top + (height - down * scale) / 2
    return {i: (x0 + (c - min(columns)) * scale, y0 + (r - min(rows)) * scale)
            for i, (c, r) in cells.items()}


#: A box: left, top, width, height.
Box = tuple[float, float, float, float]


def _segment_hits(a: tuple[float, float], b: tuple[float, float], box: Box) -> bool:
    """Does the segment a-b pass through the box (Liang-Barsky)?"""
    left, top, wide, high = box
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - left), (dx, left + wide - a[0]),
                 (-dy, a[1] - top), (dy, top + high - a[1])):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _overlap(a: Box, b: Box) -> bool:
    return (a[0] < b[0] + b[2] and b[0] < a[0] + a[2]
            and a[1] < b[1] + b[3] and b[1] < a[1] + a[3])


def place_labels(world: WorldMap, points: dict[int, tuple[float, float]],
                 sizes: dict[int, tuple[float, float]], radius: float,
                 gap: float, bounds: Box) -> dict[int, Box]:
    """Where each place's name goes: beside its circle, on the side that
    crosses the fewest roads, circles and other names.

    `sizes` is each name's width and height in pixels; a place without one has
    no label. The sides are tried right, left, above, below, then above and
    below with the name starting or ending at the circle, and the first with
    nothing in the way wins. When every side is in the way the one
    with the fewest things in the way does, and one inside `bounds` beats one
    outside it.
    """
    roads = [(points[r.a], points[r.b]) for r in world.roads
             if r.a in points and r.b in points]
    circles = {i: (x - radius, y - radius, 2 * radius, 2 * radius)
               for i, (x, y) in points.items()}
    placed: dict[int, Box] = {}
    for index, (x, y) in sorted(points.items()):
        if index not in sizes:
            continue
        w, h = sizes[index]
        reach = radius + gap
        sides = ((x + reach, y - h / 2), (x - reach - w, y - h / 2),
                 (x - w / 2, y - reach - h), (x - w / 2, y + reach),
                 (x - radius, y - reach - h), (x - radius, y + reach),
                 (x + radius - w, y - reach - h), (x + radius - w, y + reach))
        best = None
        for rank, (left, top) in enumerate(sides):
            box = (left, top, w, h)
            outside = not (bounds[0] <= left and left + w <= bounds[0] + bounds[2]
                           and bounds[1] <= top and top + h <= bounds[1] + bounds[3])
            hits = (sum(_segment_hits(a, b, box) for a, b in roads)
                    + sum(_overlap(box, c) for i, c in circles.items() if i != index)
                    + sum(_overlap(box, other) for other in placed.values()))
            score = (outside, hits, rank)
            if best is None or score < best[0]:
                best = (score, box)
        placed[index] = best[1]
    return placed
