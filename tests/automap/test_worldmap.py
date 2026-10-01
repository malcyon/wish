"""A world-map screen is a state of its own: no map, no marker, the last area kept."""
import pytest
from support.automapwindow import make_window
from support.stalestatus import curse_target
from test_stale_status import synthetic_map

from automap import c64
from automap.area import RESIDENT_GEO
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


@pytest.mark.parametrize("script,indoors", [(3, 0), (0x50, 1)])
def test_curse_needs_the_flag_clear_and_a_world_map_script(script, indoors):
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
    assert not win.state.notes
