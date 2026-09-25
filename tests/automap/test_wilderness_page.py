"""The outdoor picture, its two radios and the page switch, behind
`WISH_EXPERIMENTAL_WILDERNESS_MAP`. Synthetic windows whose every square is one
solid colour per window: no game bytes, no disks, no emulator."""

import pytest
from PyQt6.QtGui import QColor
from support.automapwindow import make_window

from automap import c64
from automap.config import Settings
from automap.render import CELL, CELL_MIN, MARGIN
from automap.state import WILDERNESS_ENV, AutomapState
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


def _window_on(app, tmp_path, monkeypatch, fixes, window=1, flag="1", heading=2):
    if flag is None:
        monkeypatch.delenv(WILDERNESS_ENV, raising=False)
    else:
        monkeypatch.setenv(WILDERNESS_ENV, flag)
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


# -- the flag ------------------------------------------------------------------

@pytest.mark.parametrize("flag", [None, "0", "off", ""])
def test_with_the_flag_off_there_is_no_page_and_no_radio(
        app, tmp_path, monkeypatch, flag):
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)], flag=flag)
    _step(win)
    assert win.world_canvas is None
    assert win.view_buttons == ()
    assert win.stack.currentWidget() is win.canvas
    assert win.stack.count() == 2


def test_with_the_flag_on_the_page_and_two_radios_exist(
        app, tmp_path, monkeypatch):
    win, _ = _window_on(app, tmp_path, monkeypatch, [out(8, 27)])
    assert win.world_canvas is not None
    assert [b.text() for b in win.view_buttons] == ["Full View", "Area View"]
    assert win.stack.count() == 3


# -- the status bar's controls -------------------------------------------------

def test_the_radios_show_outdoors_and_fog_of_war_indoors(
        app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QStatusBar
    win, _ = _window_on(app, tmp_path, monkeypatch,
                        [indoors(), out(8, 27), indoors()])
    bar = QStatusBar()
    for widget in (*win.view_buttons, win.fog_box):
        bar.addPermanentWidget(widget)
    win.fog_box.setChecked(True)
    win.show_controls(True)

    def shown():
        return (win.fog_box.isVisibleTo(bar),
                tuple(b.isVisibleTo(bar) for b in win.view_buttons))
    _step(win)
    assert shown() == (True, (False, False))
    _step(win)
    assert shown() == (False, (True, True))
    _step(win)
    assert shown() == (True, (False, False))
    assert win.fog_box.isChecked() and win.state.reveal
    win.show_controls(False)
    assert shown() == (False, (False, False))


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
