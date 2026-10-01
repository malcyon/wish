"""Curse's world map as a route diagram in the automapper tab.

The reader (`goldbox.curse_worldmap`) is tested on its own. What is asked here
is what a player sees: the places at the game's marker cells, the party's
place filled in, the strip naming it, and the ordinary blank canvas wherever
nothing could be read. The synthetic world uses made-up names and cells.
"""
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
from automap.window import PAPER, PARTY, AutomapBinding
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
def test_no_name_runs_off_the_widget_at_any_font(app, extra):
    from automap.window import RouteCanvas
    canvas = RouteCanvas(None)
    font = QFont(canvas.font())
    font.setPointSizeF(font.pointSizeF() + extra)
    canvas.setFont(font)
    canvas.resize(canvas.sizeHint())
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
