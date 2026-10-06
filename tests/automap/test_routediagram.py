"""Curse's world map as a route diagram in the automapper tab.

The reader (`goldbox.curse_worldmap`) is tested on its own. What is asked here
is what a player sees: the places at the game's marker cells, the party's
place filled in, the strip naming it, and the ordinary blank canvas wherever
nothing could be read. The synthetic world uses made-up names and cells.
"""
from dataclasses import replace
from types import SimpleNamespace

import gamedata
import pytest
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QApplication, QMainWindow
from test_stale_status import synthetic_map

from automap import routes
from automap.area import RESIDENT_GEO
from automap.render import MARGIN
from automap.state import Automapper
from automap.target import Fix, ReplayTarget
from automap.window import INK, PAPER, PARTY, AutomapBinding
from goldbox import c64_port
from goldbox.curse_worldmap import Leg, Place, Road, WorldMap, WorldMapError

CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
POOL = c64_port.POOL_OF_RADIANCE
SILVER = c64_port.SECRET_OF_THE_SILVER_BLADES


WORLD_MAP = Fix(0, 0, None, "memory", None, world_map=True)


def world_fix(node, leg=None):
    """A fix on the world map with the party at this place."""
    return Fix(0, 0, None, "memory", None, world_map=True, world_node=node,
               world_leg=leg)


def leg(source, target):
    return Leg(source * 4, source, 0, target, False, None, None)


def synthetic_world(cells=((2, 3), (12, 3), (12, 9), (30, 9), (2, 15))):
    """Five made-up places on made-up cells, road-linked in a chain and one
    loop. Named in the capitals the game prints."""
    names = ("ALPHATOWN", "BETA FORD", "GAMMA KEEP", "DELTA", "EPSILON ROCK")
    places = tuple(Place(i, names[i], 0x50, (), cells[i]) for i in range(5))
    pairs = ((0, 1), (1, 2), (2, 3), (0, 4), (1, 4))
    roads = tuple(Road(a, b, leg(a, b), leg(b, a)) for a, b in pairs)
    return WorldMap(places, (), roads, cells)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def fake_disks(monkeypatch, world=None, files=("ECL50", "ECL51", "GDRIVE02")):
    """The loader sees these files and the reader answers with `world`, or
    raises when it is an exception. Returns the list of reader calls."""
    calls = []
    monkeypatch.setattr(routes, "_read_files",
                        lambda disks, game, names: {n: b"" for n in files})

    def read(scripts, driver):
        calls.append(sorted(scripts))
        if isinstance(world, Exception):
            raise world
        return world

    monkeypatch.setattr(routes, "read_world_map", read)
    return calls


def window(app, tmp_path, monkeypatch, game=CURSE, fixes=(WORLD_MAP,)):
    sewers = synthetic_map(2)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    mapper = Automapper(ReplayTarget(list(fixes), {RESIDENT_GEO: sewers.to_bytes()}),
                        {"GEO03": sewers}, area="GEO03", title=game.title)
    win = AutomapBinding(root, mapper, disks=str(tmp_path))
    return win


def on_the_world_map(win):
    win.mapper.poll()
    win._refresh()
    assert win.state.world_map
    # A widget in a window that is not shown takes its size from the layout at
    # its first grab, so take it before anything is measured.
    win.route_canvas.grab()


def pixel(widget, x, y) -> QColor:
    return widget.grab().toImage().pixelColor(round(x), round(y))


def dark(colour: QColor) -> bool:
    return colour.lightness() < PAPER.lightness() - 80


# -- the layout ----------------------------------------------------------------

def test_places_keep_the_proportions_of_their_marker_cells():
    world = synthetic_world()
    points = routes.place_points(world, 10, 20, 600, 500)
    across = points[3][0] - points[0][0]
    down = points[4][1] - points[0][1]
    assert across / down == pytest.approx((30 - 2) / (15 - 3))
    # One scale both ways, the farthest cells touching the nearer edges.
    assert max(x for x, _ in points.values()) - min(x for x, _ in points.values()) \
        == pytest.approx(600)
    assert all(10 <= x <= 610 and 20 <= y <= 520 for x, y in points.values())


def test_an_amiga_only_folder_gives_the_route_page_with_the_amigas_cells():
    import pathlib

    from automap import gamedisks
    folder = next((p for where in gamedisks.candidates("amiga")
                   for p in sorted(pathlib.Path(where).glob("Curse*"))
                   if list(p.glob("*_A.adf")) and list(p.glob("*_B.adf"))), None)
    if folder is None:
        pytest.skip("needs the Amiga Curse disks")
    world = routes.load_route_map(folder, CURSE)
    assert world is not None and len(world.places) == 14
    assert len(world.roads) == 20
    assert all(p.cell is not None for p in world.places)
    assert world.cells[:14] == tuple(p.cell for p in world.places)


def _worldmap_tests():
    """The reader's test module, loaded by path: its synthetic Amiga program
    is the one builder, and the two test folders do not share an import path."""
    import importlib.util
    import pathlib
    path = (pathlib.Path(__file__).parents[1] / "curse_of_the_azure_bonds"
            / "test_curse_worldmap.py")
    spec = importlib.util.spec_from_file_location("curse_worldmap_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _amiga_curse_folder(tmp_path, program=True, scripts=True):
    """A folder of synthetic Amiga Curse disks: A carries the program and B the
    script library, each block holding a marker string for its area."""
    from goldbox.amiga_adf import AmigaDisk
    amiga_program = _worldmap_tests().amiga_program
    disk_a = AmigaDisk.blank("Curse A")
    disk_a.write_file("/Curse", amiga_program([3, 11, 20], [14, 6, 10]))
    disk_b = AmigaDisk.blank("Curse B")
    disk_b.make_dir("/DISKB")
    table = (2).to_bytes(2, "big") + b"".join(
        a.to_bytes(2, "big") + b.to_bytes(2, "big")
        for a, b in ((0x50, 1), (0x51, 2)))
    blocks = [table, b"script50", b"script51"]
    offsets, at = [], 16 + 4 * (len(blocks) + 1)
    for block in blocks:
        offsets.append(at)
        at += len(block)
    offsets.append(at)
    glb = (b"GLIB" + bytes(4) + len(blocks).to_bytes(2, "big") + bytes(2)
           + b"DATA" + b"".join(o.to_bytes(4, "big") for o in offsets)
           + b"".join(blocks))
    disk_b.write_file("/DISKB/ECL.GLB", glb)
    if program:
        disk_a.save(tmp_path / "curse_a.adf")
    if scripts:
        disk_b.save(tmp_path / "curse_b.adf")
    return tmp_path


def _read_by_recording(monkeypatch):
    calls = []

    def read(scripts, driver=None, cells=None):
        calls.append((dict(scripts), driver, cells))
        return synthetic_world()

    monkeypatch.setattr(routes, "read_world_map", read)
    return calls


def test_synthetic_amiga_disks_give_the_route_page(tmp_path, monkeypatch):
    calls = _read_by_recording(monkeypatch)
    folder = _amiga_curse_folder(tmp_path)
    assert routes.load_route_map(folder, CURSE) is not None
    [(scripts, driver, cells)] = calls
    assert scripts == {"ECL50": b"script50", "ECL51": b"script51"}
    assert driver is None and cells == ((3, 14), (11, 6), (20, 10))


@pytest.mark.parametrize("missing", ["program", "scripts"])
def test_one_amiga_disk_missing_gives_no_route_page(tmp_path, monkeypatch,
                                                    missing):
    calls = _read_by_recording(monkeypatch)
    folder = _amiga_curse_folder(tmp_path, **{missing: False})
    assert routes.load_route_map(folder, CURSE) is None
    assert calls == []


def test_c64_files_win_over_amiga_disks(tmp_path, monkeypatch):
    calls = fake_disks(monkeypatch, synthetic_world())
    folder = _amiga_curse_folder(tmp_path)
    monkeypatch.setattr(routes, "_read_amiga", lambda *a: pytest.fail("Amiga"))
    assert routes.load_route_map(folder, CURSE) is not None
    assert calls == [["ECL50", "ECL51"]]


def test_a_partly_read_amiga_disk_is_logged_at_debug_level(
        tmp_path, monkeypatch, caplog):
    from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
    folder = _amiga_curse_folder(tmp_path)
    real = AmigaDisk.read_file

    def read(self, path):
        if path.upper().endswith("ECL.GLB"):
            raise AmigaDiskError("broken chain")
        return real(self, path)

    monkeypatch.setattr(AmigaDisk, "read_file", read)
    with caplog.at_level("DEBUG", logger="wish.automap.routes"):
        assert routes._read_amiga(folder, CURSE, ("ECL50",)) is None
    assert any("curse_b.adf" in r.getMessage() and "broken chain"
               in r.getMessage() for r in caplog.records)


def test_the_drawing_is_centred_in_the_room_it_is_given():
    points = routes.place_points(synthetic_world(), 0, 0, 280, 1000)
    ys = [y for _, y in points.values()]
    assert (min(ys) + max(ys)) / 2 == pytest.approx(500)


def test_a_name_goes_where_no_road_circle_or_name_is():
    world = synthetic_world()
    points = routes.place_points(world, 40, 40, 520, 400)
    sizes = {i: (60, 14) for i in points}
    bounds = (0, 0, 600, 480)
    boxes = routes.place_labels(world, points, sizes, 7, 4, bounds)
    assert set(boxes) == set(points)
    roads = [(points[r.a], points[r.b]) for r in world.roads]
    for i, box in boxes.items():
        assert not any(routes._segment_hits(a, b, box) for a, b in roads)
        assert not any(routes._overlap(
            box, (x - 7, y - 7, 14, 14)) for j, (x, y) in points.items() if j != i)
        assert bounds[0] <= box[0] and box[0] + box[2] <= bounds[2]
        assert bounds[1] <= box[1] and box[1] + box[3] <= bounds[3]
    for i, box in boxes.items():
        assert not any(routes._overlap(box, other)
                       for j, other in boxes.items() if j != i)


# -- the canvas ----------------------------------------------------------------

def test_the_diagram_draws_a_circle_at_each_place_the_reader_gives(
        app, tmp_path, monkeypatch):
    fake_disks(monkeypatch, synthetic_world())
    win = window(app, tmp_path, monkeypatch, fixes=[world_fix(node=1)])
    on_the_world_map(win)
    canvas = win.route_canvas
    points = canvas.points
    assert len(points) == 5
    for i, (x, y) in points.items():
        ring = pixel(canvas, x + canvas.NODE_RADIUS, y)
        assert dark(ring), f"no circle at place {i}"
        assert pixel(canvas, x, y) in (PAPER, PARTY)
    # And only there: the middle of the widget's empty corner is bare paper.
    assert pixel(canvas, canvas.width() - 3, 3) == PAPER


def test_a_place_is_drawn_where_its_cell_puts_it(app, tmp_path, monkeypatch):
    world = synthetic_world()
    shifted = WorldMap(world.places[:4] + (Place(4, "EPSILON ROCK", 0x50, (), (2, 11)),),
                       (), world.roads, world.cells)
    fake_disks(monkeypatch, shifted)
    win = window(app, tmp_path, monkeypatch, fixes=[world_fix(node=0)])
    on_the_world_map(win)
    canvas = win.route_canvas
    room = (MARGIN, MARGIN, canvas.width() - 2 * MARGIN, canvas.height() - 2 * MARGIN)
    x, y = routes.place_points(shifted, *room)[4]
    old = routes.place_points(world, *room)[4]
    assert abs(y - old[1]) > canvas.NODE_RADIUS
    assert dark(pixel(canvas, x + canvas.NODE_RADIUS, y))
    assert not dark(pixel(canvas, old[0] + canvas.NODE_RADIUS, old[1]))


def test_the_party_place_is_filled_and_no_other(app, tmp_path, monkeypatch):
    fake_disks(monkeypatch, synthetic_world())
    win = window(app, tmp_path, monkeypatch, fixes=[world_fix(node=2)])
    on_the_world_map(win)
    canvas = win.route_canvas
    centres = {i: pixel(canvas, x, y) for i, (x, y) in canvas.points.items()}
    assert centres[2] == PARTY
    assert all(colour == PAPER for i, colour in centres.items() if i != 2)


def test_the_highlight_follows_the_party(app, tmp_path, monkeypatch):
    fake_disks(monkeypatch, synthetic_world())
    win = window(app, tmp_path, monkeypatch,
                 fixes=[world_fix(node=1), world_fix(node=3)])
    on_the_world_map(win)
    canvas = win.route_canvas
    assert pixel(canvas, *canvas.points[1]) == PARTY
    win.mapper.poll()
    win._refresh()
    assert pixel(canvas, *canvas.points[3]) == PARTY
    assert pixel(canvas, *canvas.points[1]) == PAPER


def test_a_destination_changes_nothing_on_the_diagram(app, tmp_path, monkeypatch):
    fake_disks(monkeypatch, synthetic_world())
    win = window(app, tmp_path, monkeypatch,
                 fixes=[world_fix(node=1, leg=2), world_fix(node=1, leg=0xFF)])
    on_the_world_map(win)
    travelling = win.route_canvas.grab().toImage()
    win.mapper.poll()
    win._refresh()
    assert win.route_canvas.grab().toImage() == travelling


@pytest.mark.parametrize("extra", [0, 6, 10])
@pytest.mark.parametrize("size", ["sizeHint", "minimumSize"])
def test_no_name_runs_off_the_widget_at_any_font(app, extra, size):
    from automap.window import RouteCanvas
    canvas = RouteCanvas(None)
    font = QFont(canvas.font())
    font.setPointSizeF(font.pointSizeF() + extra)
    canvas.setFont(font)
    canvas.resize(getattr(canvas, size)())
    canvas.show_map(synthetic_world())
    metrics = canvas.fontMetrics()
    names = {p.index: routes.display_name(p.name) for p in canvas.route.places}
    sizes = {i: (metrics.horizontalAdvance(n), metrics.height())
             for i, n in names.items()}
    boxes = routes.place_labels(canvas.route, canvas.points, sizes,
                                canvas.NODE_RADIUS, canvas.LABEL_GAP,
                                (0, 0, canvas.width(), canvas.height()))
    assert all(0 <= left and left + w <= canvas.width()
               and 0 <= top and top + h <= canvas.height()
               for left, top, w, h in boxes.values())


# -- the roads -----------------------------------------------------------------

def line_world():
    """Five places in one row with a road between each pair: a one-way road
    running right, an ordinary two-way road, a conditional one, a one-way road
    running left, and a conditional one-way road running right."""
    cells = tuple((c, 5) for c in (0, 20, 40, 60, 80, 100))
    places = tuple(Place(i, f"P{i}", 0x50, (), cells[i]) for i in range(6))
    roads = (
        Road(0, 1, leg(0, 1), None),
        Road(1, 2, leg(1, 2), leg(2, 1)),
        Road(2, 3, replace(leg(2, 3), conditional=True), leg(3, 2)),
        Road(3, 4, None, leg(4, 3)),
        Road(4, 5, replace(leg(4, 5), conditional=True), None),
    )
    return WorldMap(places, (), roads, cells)


@pytest.fixture
def row(app):
    """A canvas drawing `line_world`, laid out by one grab, and its points."""
    from automap.window import RouteCanvas
    canvas = RouteCanvas(SimpleNamespace(world_node=None))
    canvas.resize(900, 160)
    canvas.show_map(line_world())
    canvas.grab()
    return canvas, canvas.points


def road_columns(canvas, points, a, b):
    """The image and the x positions along the road between two places that
    lie clear of both circles."""
    image = canvas.grab().toImage()
    reach = canvas.NODE_RADIUS + 3
    return image, range(round(points[a][0]) + reach, round(points[b][0]) - reach)


def inked(image, x, y) -> bool:
    """Is there ink in this column within a pixel of the road's row?"""
    return any(dark(image.pixelColor(x, row)) for row in (y - 1, y, y + 1))


def thickness(image, x, y) -> int:
    """How many pixels of the column through x are ink, within 12 of the row."""
    return sum(dark(image.pixelColor(x, row)) for row in range(y - 12, y + 13))


def middle_widths(canvas, points, a, b):
    """The ink across the road a little before its middle and a little after,
    along the x axis."""
    image, xs = road_columns(canvas, points, a, b)
    mid, y = (xs.start + xs.stop) // 2, round(points[a][1])
    return thickness(image, mid - 5, y), thickness(image, mid + 5, y)


def test_a_one_way_road_has_an_arrowhead_pointing_the_way_it_runs(row):
    canvas, points = row
    behind, ahead = middle_widths(canvas, points, 0, 1)
    assert behind >= 12 and ahead <= 8          # wide base, then the point
    behind, ahead = middle_widths(canvas, points, 3, 4)
    assert ahead >= 12 and behind <= 8          # the other road runs left


def test_a_two_way_road_has_no_arrowhead(row):
    canvas, points = row
    for pair in ((1, 2), (2, 3)):
        assert max(middle_widths(canvas, points, *pair)) <= 4, pair


def test_an_arrowhead_is_centred_on_the_middle_of_its_road():
    from automap.routes import arrowhead
    tip, left, right = arrowhead((10, 40), (110, 40), length=20, half_width=6)
    assert tip == (70, 40)
    assert left[0] == right[0] == 50 and {left[1], right[1]} == {34, 46}
    assert arrowhead((5, 5), (5, 5)) == ()


def test_which_way_a_road_runs_comes_from_the_legs_it_has():
    from automap.routes import travel_direction
    assert travel_direction(Road(3, 7, leg(3, 7), None)) == (3, 7)
    assert travel_direction(Road(3, 7, None, leg(7, 3))) == (7, 3)
    assert travel_direction(Road(3, 7, leg(3, 7), leg(7, 3))) is None
    assert travel_direction(Road(3, 7, None, None)) is None


def test_a_conditional_leg_in_either_direction_makes_the_road_conditional():
    from automap.routes import is_conditional
    sometimes = replace(leg(1, 2), conditional=True)
    assert is_conditional(Road(1, 2, sometimes, leg(2, 1)))
    assert is_conditional(Road(1, 2, leg(1, 2), replace(leg(2, 1), conditional=True)))
    assert is_conditional(Road(1, 2, None, sometimes))
    assert not is_conditional(Road(1, 2, leg(1, 2), leg(2, 1)))
    assert not is_conditional(Road(1, 2, replace(leg(1, 2), conditional=None), None))


def ink_runs(canvas, points, a, b) -> int:
    """How many separate stretches of ink the road between two places makes,
    clear of both circles."""
    image, xs = road_columns(canvas, points, a, b)
    y = round(points[a][1])
    flags = [inked(image, x, y) for x in xs]
    return sum(1 for was, now in zip([False] + flags, flags) if now and not was)


def test_a_conditional_road_is_dashed_and_an_ordinary_one_is_not(row):
    canvas, points = row
    assert ink_runs(canvas, points, 2, 3) >= 4
    assert ink_runs(canvas, points, 1, 2) == 1
    # The dashes are the road's own colour, not a lighter one.
    image, xs = road_columns(canvas, points, 2, 3)
    y = round(points[2][1])
    assert min(image.pixelColor(x, row).lightness()
               for x in xs for row in (y - 1, y)) <= INK.lightness() + 10


def test_a_road_that_is_one_way_and_conditional_has_both_marks(row):
    canvas, points = row
    assert ink_runs(canvas, points, 4, 5) >= 4
    behind, ahead = middle_widths(canvas, points, 4, 5)
    assert behind >= 12 and ahead <= 8


# -- the window ----------------------------------------------------------------

def test_the_strip_names_the_place_and_the_tab_shows_the_diagram(
        app, tmp_path, monkeypatch):
    fake_disks(monkeypatch, synthetic_world())
    win = window(app, tmp_path, monkeypatch, fixes=[world_fix(node=2)])
    assert win.stack.currentWidget() is win.canvas
    on_the_world_map(win)
    assert win.strip.area.text() == "Gamma Keep"
    assert win.strip.where.text() == ""
    assert win.stack.currentWidget() is win.route_canvas


def test_the_strip_follows_the_party_to_the_next_place(app, tmp_path, monkeypatch):
    fake_disks(monkeypatch, synthetic_world())
    win = window(app, tmp_path, monkeypatch,
                 fixes=[world_fix(node=0), world_fix(node=3)])
    on_the_world_map(win)
    assert win.strip.area.text() == "Alphatown"
    win.mapper.poll()
    win._refresh()
    assert win.strip.area.text() == "Delta"


def test_a_place_the_reader_has_no_name_for_leaves_the_strip_empty(
        app, tmp_path, monkeypatch):
    world = synthetic_world()
    unnamed = WorldMap((Place(0, None, None, (), (2, 3)),) + world.places[1:],
                       (), world.roads, world.cells)
    fake_disks(monkeypatch, unnamed)
    win = window(app, tmp_path, monkeypatch, fixes=[world_fix(node=0)])
    on_the_world_map(win)
    assert win.strip.area.text() == ""


def test_a_party_that_leaves_the_world_map_gets_its_map_and_strip_back(
        app, tmp_path, monkeypatch):
    fake_disks(monkeypatch, synthetic_world())
    back = Fix(3, 4, 2, "memory", 501)
    win = window(app, tmp_path, monkeypatch, fixes=[world_fix(node=2), back])
    on_the_world_map(win)
    win.mapper.poll()
    win._refresh()
    assert not win.state.world_map
    assert win.stack.currentWidget() is win.canvas
    assert win.strip.area.text() != "Gamma Keep"


# -- nothing read ---------------------------------------------------------------

def blank_world_map(app, tmp_path, monkeypatch, **kw):
    """The window as part B leaves it, and the same window with a failed read."""
    fake_disks(monkeypatch, **kw)
    win = window(app, tmp_path, monkeypatch, fixes=[world_fix(node=2)])
    on_the_world_map(win)
    return win


@pytest.mark.parametrize("failure", [
    {"world": WorldMapError("a table is missing")},
    {"world": KeyError("a table nobody guarded")},
    {"world": synthetic_world(), "files": ("ECL50", "GDRIVE02")},
    {"world": synthetic_world(), "files": ()},
])
def test_a_failed_read_leaves_the_canvas_as_it_was_blank(
        app, tmp_path, monkeypatch, failure):
    win = blank_world_map(app, tmp_path, monkeypatch, **failure)
    assert not win.route_canvas.has_map
    assert win.stack.currentWidget() is win.canvas
    assert win.strip.area.text() == "" and win.strip.where.text() == ""


def test_a_place_with_no_marker_cell_is_a_failed_read(app, tmp_path, monkeypatch):
    world = synthetic_world()
    uncelled = WorldMap(world.places[:4] + (Place(4, "NOWHERE", 0x50, (), None),),
                        (), world.roads, world.cells)
    win = blank_world_map(app, tmp_path, monkeypatch, world=uncelled)
    assert not win.route_canvas.has_map
    assert win.strip.area.text() == ""


def test_the_reader_is_given_the_title_scripts_and_not_other_files(
        app, tmp_path, monkeypatch):
    calls = fake_disks(monkeypatch, synthetic_world())
    window(app, tmp_path, monkeypatch)
    assert calls == [["ECL50", "ECL51"]]


@pytest.mark.parametrize("game", [POOL, SILVER])
def test_other_titles_keep_the_blank_canvas(app, tmp_path, monkeypatch, game):
    calls = fake_disks(monkeypatch, synthetic_world())
    win = window(app, tmp_path, monkeypatch, game=game, fixes=[WORLD_MAP])
    assert calls == []
    assert not win.route_canvas.has_map
    win.mapper.poll()
    win._refresh()
    assert win.stack.currentWidget() is win.canvas
    assert win.strip.area.text() == ""


def test_no_disks_leaves_the_blank_canvas(app, tmp_path, monkeypatch):
    calls = fake_disks(monkeypatch, synthetic_world())
    win = window(app, tmp_path, monkeypatch)
    assert win.route_canvas.has_map
    win.set_maps({}, title=CURSE.title, disks=None)
    assert not win.route_canvas.has_map
    assert calls == [["ECL50", "ECL51"]]


# -- the player's own disks -----------------------------------------------------

@gamedata.needs_curse_disks
def test_the_player_disks_give_curse_fourteen_named_places(app, tmp_path, monkeypatch):
    # The reader's own tests pin the names and roads; this is the loader.
    world = routes.load_route_map(gamedata.curse_dir(), CURSE)
    assert world is not None
    assert len(world.places) == 14 and len(world.roads) == 20
    assert all(p.cell is not None and p.name for p in world.places)
    win = window(app, tmp_path, monkeypatch, fixes=[world_fix(node=1)])
    win.set_maps({}, title=CURSE.title, disks=str(gamedata.curse_dir()))
    on_the_world_map(win)
    assert win.route_canvas.has_map
    assert win.strip.area.text() == routes.display_name(world.places[1].name)
