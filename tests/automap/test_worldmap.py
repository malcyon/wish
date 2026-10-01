"""A world-map screen is a state of its own: no map, no marker, the last area kept."""
import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from support.automapwindow import make_window
from support.stalestatus import curse_target
from test_stale_status import synthetic_map

from automap import c64
from automap.area import RESIDENT_GEO
from automap.notes import Note
from automap.render import CELL, MARGIN
from automap.state import Automapper, AutomapState
from automap.target import Fix, ReplayTarget, party_fix
from goldbox import c64_port

CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
POOL = c64_port.POOL_OF_RADIANCE
SILVER = c64_port.SECRET_OF_THE_SILVER_BLADES
WORLD_MAP = Fix(0, 0, None, "memory", None, world_map=True)


def world_target(game=CURSE, indoors=0, script=0x50, node=(3, 7)):
    """No status line, `$C04B` as the world map leaves it, flag and script set."""
    target = curse_target("", (33, 208, 202))
    base = game.save_load_address
    target.memory[base + 0xE6] = bytes([indoors])
    target.memory[base + 0xF2] = bytes([script])
    target.memory[base + 0x19B] = bytes(node)
    return target


def test_a_curse_machine_on_the_world_map_gives_a_world_map_fix():
    fix = party_fix(world_target().read, CURSE)
    assert fix.world_map
    assert (fix.world_node, fix.world_leg) == (3, 7)


@pytest.mark.parametrize("game", [POOL, SILVER])
def test_the_same_bytes_on_other_titles_are_not_a_world_map(game):
    fix = party_fix(world_target(game).read, game)
    assert fix is None or not fix.world_map


@pytest.mark.parametrize("script,indoors", [(3, 0), (3, 1)])
def test_curse_needs_a_world_map_script(script, indoors):
    fix = party_fix(world_target(script=script, indoors=indoors).read, CURSE)
    assert fix is None or not fix.world_map


def test_the_indoors_flag_gate_of_the_travel_grid_is_not_widened():
    assert c64.machine_for(CURSE).indoors_flag_base is None
    assert c64.machine_for(CURSE).world_map_flag_base == 0x4BE6
    assert c64.machine_for(POOL).world_map_flag_base is None


def mapper_in_the_sewers(tmp_path, monkeypatch, fixes):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    sewers = synthetic_map(2)
    target = ReplayTarget(fixes, {RESIDENT_GEO: sewers.to_bytes()})
    return Automapper(target, {"GEO03": sewers}, area="GEO03", title=CURSE.title)


def test_the_world_map_keeps_the_last_area_and_the_return_lands_in_it(
        tmp_path, monkeypatch):
    mapper = mapper_in_the_sewers(tmp_path, monkeypatch, [
        Fix(14, 15, 2, "status", 500), WORLD_MAP,
        Fix(0, 0, 2, "memory", 501)])
    state = mapper.state
    mapper.poll()
    seen = len(state.exploration)
    assert mapper.poll() is True
    assert state.world_map and state.area_label == ""
    assert (state.area, state.x, state.y) == ("GEO03", 14, 15)
    assert len(state.exploration) == seen
    mapper.poll()
    assert not state.world_map
    assert (state.area, state.x, state.y) == ("GEO03", 0, 0)


def test_the_state_carries_the_town_for_a_later_diagram(tmp_path, monkeypatch):
    mapper = mapper_in_the_sewers(tmp_path, monkeypatch, [
        Fix(14, 15, 2, "status", 500),
        Fix(0, 0, None, "memory", None, world_map=True, world_node=3,
            world_leg=7)])
    mapper.poll()
    mapper.poll()
    assert (mapper.state.world_node, mapper.state.world_leg) == (3, 7)


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_window_draws_no_map_and_says_nothing_on_the_world_map(
        app, tmp_path, monkeypatch):
    sewers = synthetic_map(2)
    fixes = [Fix(5, 5, 2, "status", 500), WORLD_MAP]
    win = make_window(app, tmp_path, monkeypatch,
                      ReplayTarget(fixes, {RESIDENT_GEO: sewers.to_bytes()}),
                      maps={"GEO03": sewers}, area="GEO03")
    win.mapper.poll()
    win._refresh()
    indoor = win.canvas.grab().toImage()
    win.mapper.poll()
    win._refresh()
    assert win.strip.where.text() == "" and win.strip.area.text() == ""
    assert win.canvas.grab().toImage() != indoor
    # The canvas with nothing on it is what the travel grid leaves bare.
    reference = win.canvas.state
    win.canvas.state = bare = AutomapState()
    bare.outdoors = True
    try:
        blank = win.canvas.grab().toImage()
    finally:
        win.canvas.state = reference
    assert win.canvas.grab().toImage() == blank
    win.note_here()
    assert win._popover is None


def window_on_the_world_map(app, tmp_path, monkeypatch):
    sewers = synthetic_map(2)
    fixes = [Fix(5, 5, 2, "status", 500), WORLD_MAP]
    win = make_window(app, tmp_path, monkeypatch,
                      ReplayTarget(fixes, {RESIDENT_GEO: sewers.to_bytes()}),
                      maps={"GEO03": sewers}, area="GEO03")
    win.state.add_note(5, 5, Note("dueling pairs", "encounter"))
    win.mapper.poll()
    win.mapper.poll()
    win._refresh()
    win.canvas.resize(win.canvas.sizeHint())
    assert win.state.world_map
    return win


def test_the_canvas_offers_no_tooltip_on_the_world_map(app, tmp_path, monkeypatch):
    win = window_on_the_world_map(app, tmp_path, monkeypatch)
    px = MARGIN + 5 * CELL + 2
    assert win.canvas.tooltip_at(px, px) is None


def test_a_click_on_the_world_map_canvas_opens_no_popover(app, tmp_path, monkeypatch):
    win = window_on_the_world_map(app, tmp_path, monkeypatch)
    at = QPointF(MARGIN + 5 * CELL + 2, MARGIN + 5 * CELL + 2)
    for kind in (QMouseEvent.Type.MouseButtonPress,
                 QMouseEvent.Type.MouseButtonRelease):
        event = QMouseEvent(kind, at, at, Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        if kind == QMouseEvent.Type.MouseButtonPress:
            win.canvas.mousePressEvent(event)
        else:
            win.canvas.mouseReleaseEvent(event)
    app.processEvents()
    assert win._popover is None


def test_a_return_to_another_area_names_it_and_clears_the_town(
        tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    sewers, cellar = synthetic_map(2), synthetic_map(3)
    target = ReplayTarget(
        [Fix(14, 15, 2, "status", 500),
         Fix(0, 0, None, "memory", None, world_map=True, world_node=3,
             world_leg=7),
         Fix(1, 1, 2, "memory", 501)],
        {RESIDENT_GEO: sewers.to_bytes()})
    mapper = Automapper(target, {"GEO03": sewers, "GEO04": cellar},
                        area="GEO03", title=CURSE.title)
    state = mapper.state
    mapper.poll()
    mapper.poll()
    assert state.world_node == 3
    target._memory[RESIDENT_GEO] = cellar.to_bytes()
    mapper.poll()
    assert not state.world_map
    assert state.area == "GEO04"
    assert (state.world_node, state.world_leg) == (None, None)


def test_the_world_map_lasts_until_the_script_id_leaves_it(tmp_path, monkeypatch):
    """SEARCH AREA's return raises `$4BE6` and shows a transient 8,8 while `$4BF2`
    still names the world map; neither is the sewers."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    sewers = synthetic_map(2)
    target = world_target()
    target.memory.update(curse_target("", (0, 0, 2), sewers).memory)
    base = CURSE.save_load_address

    def set_bytes(indoors, script, triple):
        target.memory[base + 0xE6] = bytes([indoors])
        target.memory[base + 0xF2] = bytes([script])
        target.memory[0xC04B] = bytes(triple)

    set_bytes(1, 3, (0, 0, 2))
    mapper = Automapper(target, {"GEO03": sewers}, area="GEO03", title=CURSE.title)
    state = mapper.state
    mapper.poll()
    set_bytes(0, 0x50, (33, 208, 202))
    mapper.poll()
    assert state.world_map
    set_bytes(1, 0x50, (8, 8, 2))
    for _ in range(mapper.RESIDENT_EVERY * 2):
        mapper.poll()
    assert state.world_map
    set_bytes(1, 0x50, (33, 208, 202))
    mapper.poll()
    set_bytes(1, 3, (0, 0, 2))
    for _ in range(mapper.RESIDENT_EVERY * 2):
        mapper.poll()
    assert not state.world_map
    assert (state.area, state.x, state.y, state.facing) == ("GEO03", 0, 0, 2)
    assert (8, 8) not in state.exploration
