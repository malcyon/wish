"""The outdoor picture, its two radios and the page switch. Synthetic windows whose every square is one
solid colour per window: no game bytes, no disks, no emulator."""

import pytest
from PyQt6.QtGui import QColor
from support.automapwindow import make_window

from automap import c64
from automap.config import Settings
from automap.render import CELL, CELL_MIN, MARGIN
from automap.state import AutomapState
from automap.target import Fix, ReplayTarget
from automap.window import (
    AREA_VIEW,
    FULL_VIEW,
    TRAVEL_FILL,
    WorldCanvas,
)
from goldbox.icons import C64_PALETTE
from goldbox.world import (
    CHARSET_GLYPHS,
    GLYPH_BYTES,
    GRID_SIZE,
    TILE_TABLE_SIZE,
    WORLD_ACROSS,
    WORLD_DOWN,
    Window,
    World,
)

BASE = c64.RESIDENT_WINDOW
HEADING = c64.TRAVEL_HEADING
#: Window `k` is drawn solid in colour `COLOUR + k`, so the picture says which
#: window answered each square.
COLOUR = 2
#: A tile no `_grid` square names, in a colour no window uses, for a test that
#: needs the game to paint one square differently.
PAINT_CODE, PAINT_COLOUR = 100, 6


def _grid(seed: int) -> bytes:
    return bytes((i * (seed + 3) + seed) % 100 for i in range(GRID_SIZE))


def _world() -> World:
    windows = []
    for k in range(3):
        tiles = bytearray(TILE_TABLE_SIZE)
        for entry in range(120):
            at = entry * 18
            tiles[at:at + 9] = bytes([0x40]) * 9             # glyph 0, all set
            tiles[at + 9:at + 18] = bytes([COLOUR + k]) * 9  # hi-res colour
        at = PAINT_CODE * 18
        tiles[at + 9:at + 18] = bytes([PAINT_COLOUR]) * 9
        windows.append(Window(_grid(k) + bytes(tiles)))
    glyphs = bytes([0xFF]) * (CHARSET_GLYPHS * GLYPH_BYTES)
    return World(tuple(windows), (glyphs,) * 3)


def _rgb(colour: int) -> int:
    return QColor(C64_PALETTE[colour]).rgb()


class Target(ReplayTarget):
    def __init__(self, fixes, block, heading=2):
        super().__init__(fixes)
        self.block = block
        self.heading = heading

    def read(self, addr, length):
        if addr == BASE:
            return self.block
        if addr == HEADING:
            return bytes([self.heading])
        return bytes(length)


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def out(x, y):
    return Fix(x, y, None, "status", 1000, outdoors=True)


def indoors(x=3, y=3):
    return Fix(x, y, 0, "status", 1001)


def _window_on(app, tmp_path, monkeypatch, fixes, window=1, heading=2):
    target = Target(fixes, _grid(window), heading)
    win = make_window(app, tmp_path, monkeypatch, target)
    win.set_world(_world())
    return win, target


def _step(win):
    win.mapper.poll()
    win._refresh()


def _canvas(heading, at=(1, 8, 27), view=FULL_VIEW, minimum=False):
    st = AutomapState()
    st.outdoors, st.window, st.x, st.y, st.heading = True, at[0], at[1], at[2], heading
    canvas = WorldCanvas(st)
    canvas.show_world(_world())
    canvas.set_view(view)
    canvas.resize(canvas.minimumSize() if minimum else canvas.sizeHint())
    return canvas


# -- the page ------------------------------------------------------------------

def test_the_world_page_shows_outdoors_and_the_map_page_indoors(
        app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27), indoors()])
    _step(win)
    assert win.stack.currentWidget() is win.world_canvas
    _step(win)
    assert win.stack.currentWidget() is win.canvas


def test_a_fight_on_the_grid_ends_on_the_world_page(app, tmp_path, monkeypatch):
    from gamedata import synthetic_arena

    from automap import combat
    from automap.target import MemoryTarget
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    _step(win)
    win.battle = combat.read_battle(MemoryTarget(synthetic_arena()))
    win.stack.setCurrentWidget(win.battle_canvas)
    assert win.poll_battle() is False
    assert win.stack.currentWidget() is win.world_canvas


def test_a_fight_indoors_ends_on_the_map_page(app, tmp_path, monkeypatch):
    from gamedata import synthetic_arena

    from automap import combat
    from automap.target import MemoryTarget
    win, _ = _window_on(app, tmp_path, monkeypatch, [indoors()])
    _step(win)
    win.battle = combat.read_battle(MemoryTarget(synthetic_arena()))
    win.stack.setCurrentWidget(win.battle_canvas)
    win.poll_battle()
    assert win.stack.currentWidget() is win.canvas


def test_an_unidentified_window_keeps_the_map_page(app, tmp_path, monkeypatch):
    win, target = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    target.block = bytes(GRID_SIZE)
    _step(win)
    assert win.stack.currentWidget() is win.canvas


def test_disks_without_glyphs_keep_the_map_page(app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    win.set_world(World(_world().windows))          # no charsets
    _step(win)
    assert win.stack.currentWidget() is win.canvas


# -- the widgets ----------------------------------------------------------------

def test_the_page_and_two_radios_exist(
        app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    assert win.world_canvas is not None
    assert [b.text() for b in win.view_buttons] == ["Full View", "Area View"]
    assert win.stack.count() == 4


# -- the radios' place and visibility ------------------------------------------

def test_the_radios_sit_in_a_row_between_the_map_and_the_buttons(
        app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QWidget
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    column = win.root.findChild(QWidget, "map_column")
    actions = win.root.findChild(QWidget, "actions_bar")
    bar = win.view_bar
    assert all(bar.isAncestorOf(b) for b in win.view_buttons)
    layout = column.layout()
    order = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert order.index(win.stack) < order.index(bar) < order.index(actions)
    row = bar.layout()
    assert [row.itemAt(i).widget() for i in range(row.count())] \
        == list(win.view_buttons)


def test_the_radios_show_outdoors_and_not_indoors(
        app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch,
                        [indoors(), out(8, 27), indoors()])
    win.fog_box.setChecked(True)
    win.show_controls(True)

    def shown():
        return (win.fog_box.isVisibleTo(win.root),
                tuple(b.isVisibleTo(win.root) for b in win.view_buttons))
    assert shown()[1] == (False, False)          # before any fix
    _step(win)
    assert shown() == (True, (False, False))
    _step(win)
    assert shown() == (False, (True, True))
    _step(win)
    assert shown() == (True, (False, False))
    assert win.fog_box.isChecked() and win.state.reveal


def test_the_radios_need_no_word_from_the_host(app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    _step(win)
    assert all(b.isVisibleTo(win.root) for b in win.view_buttons)


def test_the_hidden_radios_keep_their_row(app, tmp_path, monkeypatch):
    """The map must not change size between a town and the wilderness."""
    win, _ = _window_on(app, tmp_path, monkeypatch, [indoors(), out(8, 27)])
    win.root.resize(1300, 800)
    win.root.show()
    _step(win)
    app.processEvents()
    indoor = win.stack.height()
    _step(win)
    app.processEvents()
    assert win.stack.height() == indoor


def test_the_radios_are_hidden_during_a_fight_on_the_grid(
        app, tmp_path, monkeypatch):
    from gamedata import synthetic_arena

    from automap import combat
    from automap.target import MemoryTarget
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    win.show_controls(True)
    _step(win)
    assert all(b.isVisibleTo(win.root) for b in win.view_buttons)
    win.battle = combat.read_battle(MemoryTarget(synthetic_arena()))
    win._sync_controls()
    assert not any(b.isVisibleTo(win.root) for b in win.view_buttons)
    win.battle = None
    win._sync_controls()
    assert all(b.isVisibleTo(win.root) for b in win.view_buttons)


# -- the choice of view --------------------------------------------------------

def test_full_view_is_the_default(app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    assert win.view_buttons[0].isChecked()
    assert win.world_canvas.view == FULL_VIEW


def test_the_choice_of_view_is_remembered(app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    win.view_buttons[1].setChecked(True)
    assert win.world_canvas.view == AREA_VIEW
    assert Settings.load().wilderness_view == AREA_VIEW
    from automap.state import Automapper
    from automap.window import AutomapBinding
    again = AutomapBinding(win.root, Automapper(Target([out(8, 27)], _grid(1))),
                           settings=Settings.load())
    assert again.settings.wilderness_view == AREA_VIEW
    assert again.view_buttons[1].isChecked()
    assert again.world_canvas.view == AREA_VIEW
    again.view_buttons[0].setChecked(True)
    assert Settings.load().wilderness_view == FULL_VIEW


@pytest.mark.parametrize("junk", ["", "zoom", 3, None])
def test_anything_else_in_the_file_reads_as_full_view(junk):
    assert Settings(wilderness_view=junk).wilderness_view == FULL_VIEW


# -- the geometry --------------------------------------------------------------

@pytest.mark.parametrize("minimum", [False, True])
def test_full_view_fits_the_whole_wilderness_as_large_as_it_can(app, minimum):
    canvas = _canvas(2, minimum=minimum)
    cell = canvas.cell
    assert canvas.squares == (0, 0, WORLD_ACROSS, WORLD_DOWN)
    assert WORLD_ACROSS * cell + 2 * MARGIN <= canvas.width()
    assert WORLD_DOWN * cell + 2 * MARGIN <= canvas.height()
    # One pixel more a square would not fit.
    assert (WORLD_ACROSS * (cell + 1) + 2 * MARGIN > canvas.width()
            or WORLD_DOWN * (cell + 1) + 2 * MARGIN > canvas.height())


def test_area_view_has_the_map_pages_own_cells(app):
    canvas = _canvas(2, view=AREA_VIEW)
    assert canvas.cell == CELL
    canvas.resize(canvas.minimumSize())
    assert canvas.cell == CELL_MIN


@pytest.mark.parametrize("at, corner", [
    ((0, 2, 2), (0, 0)),                                  # top-left of the world
    ((1, 8, 27), (21 - 8, 27 - 8)),                        # mid-map: centred
    ((2, 15, 33), (WORLD_ACROSS - 16, WORLD_DOWN - 16)),   # bottom-right
])
def test_area_view_is_centred_on_the_party_and_kept_inside(app, at, corner):
    canvas = _canvas(2, at=at, view=AREA_VIEW)
    assert canvas.squares == (*corner, 16, 16)
    wx, wy = at[1] + 13 * at[0], at[2]
    assert corner[0] <= wx < corner[0] + 16 and corner[1] <= wy < corner[1] + 16


# -- what is drawn -------------------------------------------------------------

def _pixel_at_square(canvas, image, wx, wy):
    left, top, _, _ = canvas.squares
    ox, oy = canvas.origin
    cell = canvas.cell
    return image.pixel(ox + (wx - left) * cell + cell // 2,
                       oy + (wy - top) * cell + cell // 2)


@pytest.mark.parametrize("view", [FULL_VIEW, AREA_VIEW])
def test_the_marker_is_yellow_at_the_partys_world_square(app, view):
    canvas = _canvas(2, at=(1, 8, 27), view=view)
    image = canvas.grab().toImage()
    assert _pixel_at_square(canvas, image, 21, 27) == TRAVEL_FILL.rgb()
    # The square beside it is the window's own colour.
    assert _pixel_at_square(canvas, image, 23, 27) == _rgb(COLOUR + 1)


def test_the_marker_is_drawn_from_the_window_the_party_is_in(app):
    canvas = _canvas(6, at=(2, 3, 20))               # world x 29, the east window
    image = canvas.grab().toImage()
    assert _pixel_at_square(canvas, image, 29, 20) == TRAVEL_FILL.rgb()
    assert _pixel_at_square(canvas, image, 31, 20) == _rgb(COLOUR + 2)


@pytest.mark.parametrize("view", [FULL_VIEW, AREA_VIEW])
def test_no_heading_draws_no_marker(app, view):
    canvas = _canvas(None, view=view)
    image = canvas.grab().toImage()
    assert _pixel_at_square(canvas, image, 21, 27) == _rgb(COLOUR + 1)


def test_the_tiles_meet_with_no_lattice_and_no_fog(app):
    canvas = _canvas(None)
    image = canvas.grab().toImage()
    ox, oy = canvas.origin
    cell = canvas.cell
    seen = {image.pixel(ox + x, oy + y)
            for x in range(WORLD_ACROSS * cell) for y in range(WORLD_DOWN * cell)}
    assert seen == {_rgb(COLOUR), _rgb(COLOUR + 1), _rgb(COLOUR + 2)}


def test_the_marker_is_visible_at_the_narrowest_view(app):
    """At the smallest square the marker is still a triangle about a square
    wide, and not a dot inside one tile."""
    canvas = _canvas(2, minimum=True)
    image = canvas.grab().toImage()
    ox, oy = canvas.origin
    cell = canvas.cell
    yellow = [(x, y)
              for x in range(ox + 20 * cell, ox + 23 * cell)
              for y in range(oy + 26 * cell, oy + 29 * cell)
              if image.pixel(x, y) == TRAVEL_FILL.rgb()]
    assert len(yellow) >= cell * cell // 2
    assert max(x for x, _ in yellow) - min(x for x, _ in yellow) >= cell // 2


# -- the heading and the window are read outdoors and cleared on the way in ----

def test_the_heading_byte_is_read_outdoors_and_cleared_indoors(
        app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch,
                        [out(8, 27), indoors()], heading=5)
    win.mapper.poll()
    assert (win.state.window, win.state.heading) == (1, 5)
    win.mapper.poll()
    assert (win.state.window, win.state.heading) == (None, None)


def test_a_heading_outside_the_eight_is_no_heading(app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)], heading=9)
    win.mapper.poll()
    assert win.state.window == 1 and win.state.heading is None


def test_a_new_heading_is_seen_on_the_next_move(app, tmp_path, monkeypatch):
    win, target = _window_on(app, tmp_path, monkeypatch,
                             [out(8, 27), out(9, 27)], heading=2)
    win.mapper.poll()
    target.heading = 3
    assert win.mapper.poll() is True
    assert win.state.heading == 3


def _stand_to_the_cadence(win):
    """Poll until the next tick that falls on the resident cadence."""
    every = win.mapper.RESIDENT_EVERY
    while (win.mapper._ticks + 1) % every:
        win.mapper.poll()


def test_a_turn_in_place_is_seen_without_a_move(app, tmp_path, monkeypatch):
    win, target = _window_on(app, tmp_path, monkeypatch,
                             [out(8, 27)], heading=2)
    win.mapper.poll()
    target.heading = 4
    _stand_to_the_cadence(win)
    assert win.mapper.poll() is True
    assert win.state.heading == 4
    assert win.mapper.poll() is False


def _count_heading_reads(target):
    reads = []
    inner = target.read

    def read(addr, length):
        if addr == HEADING:
            reads.append(addr)
        return inner(addr, length)
    target.read = read
    return reads


def test_standing_still_reads_the_heading_once_per_cadence(
        app, tmp_path, monkeypatch):
    win, target = _window_on(app, tmp_path, monkeypatch, [out(8, 27)], heading=2)
    win.mapper.poll()
    reads = _count_heading_reads(target)
    for _ in range(win.mapper.RESIDENT_EVERY):
        win.mapper.poll()
    assert len(reads) == 1


def test_no_heading_is_read_on_standing_ticks_in_a_battle(
        app, tmp_path, monkeypatch):
    from gamedata import synthetic_arena

    from automap import combat
    from automap.target import MemoryTarget
    win, target = _window_on(app, tmp_path, monkeypatch, [out(8, 27)], heading=2)
    win.mapper.poll()
    battle = win.battle = combat.read_battle(MemoryTarget(synthetic_arena()))
    # The fight is still on at every tick, as the running game would have it.
    monkeypatch.setattr(combat, "read_battle", lambda *a, **k: battle)
    reads = _count_heading_reads(target)
    for _ in range(win.mapper.RESIDENT_EVERY):
        win.tick()
    assert reads == []


# -- what the game has painted ---------------------------------------------------

def _painted(window, square):
    """Window `window`'s disk grid with the game's paint at local `square`."""
    grid = bytearray(_grid(window))
    grid[square[1] * 18 + square[0]] = PAINT_CODE
    return bytes(grid)


def test_a_square_the_game_paints_over_keeps_its_disk_art(
        app, tmp_path, monkeypatch):
    win, target = _window_on(
        app, tmp_path, monkeypatch,
        [out(8, 27), out(8, 26), out(8, 25), out(8, 24), out(8, 23)])
    canvas = win.world_canvas
    canvas.resize(canvas.sizeHint())
    _step(win)
    target.block = _painted(1, (5, 20))
    _step(win)
    _step(win)
    image = canvas.grab().toImage()
    assert _pixel_at_square(canvas, image, 18, 20) == _rgb(COLOUR + 1)
    assert _pixel_at_square(canvas, image, 18, 20) != _rgb(PAINT_COLOUR)


def test_the_picture_is_built_once_per_world(app, tmp_path, monkeypatch):
    from automap import window as window_module
    built = []
    real = window_module.world_indices
    monkeypatch.setattr(window_module, "world_indices",
                        lambda *a, **k: built.append(1) or real(*a, **k))
    win, target = _window_on(
        app, tmp_path, monkeypatch,
        [out(8, 27), out(8, 26), out(8, 25), out(8, 24), out(8, 23)])
    assert built == [1]                             # the initial build
    _step(win)
    target.block = _painted(1, (5, 20))
    _step(win)
    _step(win)
    target.block = _painted(1, (5, 21))
    _step(win)
    _step(win)
    assert built == [1]
