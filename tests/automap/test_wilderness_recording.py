"""Recording where the party has been on the travel grid, behind
`WISH_EXPERIMENTAL_WILDERNESS_MAP`. No disks and no emulator: the windows are
synthetic and `ReplayTarget` answers `$8C00`."""

import json

import pytest
from support.automapwindow import make_window

from automap import c64
from automap.state import (
    WILDERNESS_ENV,
    Automapper,
    AutomapState,
    wilderness_enabled,
)
from automap.target import Fix, ReplayTarget
from goldbox.world import GRID_SIZE, MIN_FILE_SIZE, STRIDE, Window, World

BASE = c64.RESIDENT_WINDOW


def _window(seed: int) -> bytes:
    """A grid whose every square differs from the other windows' by position."""
    grid = bytes((i * (seed + 3) + seed) % 100 for i in range(GRID_SIZE))
    return grid


def _world() -> World:
    return World(tuple(Window(_window(i) + bytes(MIN_FILE_SIZE - GRID_SIZE))
                       for i in range(3)))


class Target(ReplayTarget):
    """Serves the given fixes; `$8C00` is `block`, which a test may swap."""

    def __init__(self, fixes, block):
        super().__init__(fixes)
        self.block = block
        self.reads = []

    def read(self, addr, length):
        if addr == BASE:
            self.reads.append(addr)
            return self.block
        return bytes(length)


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def on(monkeypatch, tmp_path):
    monkeypatch.setenv(WILDERNESS_ENV, "1")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


def mapper_for(fixes, block, world=None):
    target = Target(fixes, block)
    mapper = Automapper(target)
    mapper.use_world(world if world is not None else _world())
    return mapper, target


def out(x, y, source="status"):
    return Fix(x, y, None, source, 1000, outdoors=True)


def test_one_tick_records_the_pane_in_world_coordinates(on):
    block = _window(1)
    mapper, _ = mapper_for([out(8, 20)], block)
    assert mapper.poll() is True
    assert mapper.state.window == 1
    want = {(lx + 13, ly): (1, block[ly * STRIDE + lx])
            for ly in range(18, 23) for lx in range(6, 11)}
    assert mapper.state.wilderness == want


def test_the_pane_is_clipped_at_the_window_edges(on):
    mapper, _ = mapper_for([out(0, 0)], _window(2))
    mapper.poll()
    assert len(mapper.state.wilderness) == 9
    assert min(mapper.state.wilderness) == (26, 0)


def test_a_block_that_names_no_window_records_nothing(on):
    mapper, _ = mapper_for([out(8, 20)], bytes(GRID_SIZE))
    mapper.state.window = 2
    mapper.poll()
    assert mapper.state.wilderness == {}
    assert mapper.state.window == 2


def test_a_party_that_stands_still_does_no_read(on):
    mapper, target = mapper_for([out(8, 20)], _window(0))
    mapper.poll()
    reads = len(target.reads)
    mapper.poll()
    mapper.poll()
    assert len(target.reads) == reads


def test_a_moved_fix_reads_again(on):
    mapper, target = mapper_for([out(8, 20), out(8, 21)], _window(0))
    mapper.poll()
    mapper.poll()
    assert len(target.reads) == 2


def test_a_jump_under_the_old_window_is_held_for_one_poll(on):
    mapper, target = mapper_for(
        [out(8, 20), out(3, 20), out(3, 20)], _window(1))
    mapper.poll()
    assert mapper.poll() is False
    assert (mapper.state.x, mapper.state.y) == (8, 20)
    assert (3 + 13, 20) not in mapper.state.wilderness
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (3, 20)
    assert (3 + 13, 20) in mapper.state.wilderness


def test_a_jump_into_a_new_window_is_not_held(on):
    mapper, target = mapper_for([out(15, 27), out(3, 27)], _window(1))
    mapper.poll()
    target.block = _window(2)
    mapper.poll()
    assert mapper.state.window == 2
    assert (3 + 26, 27) in mapper.state.wilderness


def test_a_camped_party_is_believed_when_the_window_identifies(on):
    mapper, _ = mapper_for([out(8, 20, "memory")], _window(1))
    assert mapper.poll() is True
    assert mapper.state.outdoors


def test_a_camped_party_over_a_zero_page_is_still_refused(on):
    mapper, _ = mapper_for([out(8, 20, "memory")], bytes(GRID_SIZE))
    assert mapper.poll() is False
    assert not mapper.state.outdoors


def test_a_target_that_is_not_a_c64_is_never_read(on):
    mapper, target = mapper_for([out(8, 20)], _window(1))
    target.c64_memory = False
    mapper.poll()
    assert target.reads == []
    assert mapper.state.wilderness == {}


def test_the_recorded_squares_survive_a_save_and_a_load(on):
    mapper, _ = mapper_for([out(8, 20)], _window(1))
    mapper.poll()
    mapper.state.save_wilderness()
    payload = json.loads(mapper.state.wilderness_path().read_text())
    assert len(payload["seen"]) == 25
    fresh = AutomapState()
    fresh.load_wilderness()
    assert fresh.wilderness == mapper.state.wilderness


def test_forget_blanks_the_wilderness_file(on):
    from automap.maps import forget
    mapper, _ = mapper_for([out(8, 20)], _window(1))
    mapper.poll()
    mapper.state.save_wilderness()
    forget("wilderness")
    fresh = AutomapState()
    fresh.load_wilderness()
    assert fresh.wilderness == {}


def test_coming_back_indoors_saves_the_squares(on):
    mapper, _ = mapper_for([out(8, 20), Fix(3, 3, 0, "status", 1001)],
                           _window(1))
    mapper.poll()
    assert not mapper.state.wilderness_path().exists()
    mapper.poll()
    assert mapper.state.wilderness_path().exists()


def test_clear_automap_empties_memory_and_file(app, on, tmp_path, monkeypatch):
    from wish.preferences import PreferencesDialog
    target = Target([out(8, 20)], _window(1))
    win = make_window(app, tmp_path, monkeypatch, target)
    win.mapper.use_world(_world())
    win.mapper.poll()
    win.state.save_wilderness()

    class Fake:
        pass
    fake = Fake()
    fake.win = Fake()
    fake.win.mapper = win.mapper
    fake.win.map = None
    PreferencesDialog._clear_automap(fake)
    assert win.state.wilderness == {}
    assert json.loads(win.state.wilderness_path().read_text())["seen"] == []


# -- the flag ----------------------------------------------------------------

def test_the_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv(WILDERNESS_ENV, raising=False)
    assert wilderness_enabled() is False


@pytest.mark.parametrize("value", ["0", "off", "", "no", "false"])
def test_a_forgotten_value_does_not_turn_it_on(monkeypatch, value):
    monkeypatch.setenv(WILDERNESS_ENV, value)
    assert wilderness_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "ON"])
def test_the_flag_turns_it_on(monkeypatch, value):
    monkeypatch.setenv(WILDERNESS_ENV, value)
    assert wilderness_enabled() is True


def test_with_the_flag_off_nothing_is_recorded_or_read(monkeypatch, tmp_path):
    monkeypatch.delenv(WILDERNESS_ENV, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    mapper, target = mapper_for([out(8, 20, "memory")], _window(1))
    assert mapper.poll() is False           # no proof, as before
    assert target.reads == []
    assert mapper.state.wilderness == {}


# -- the addresses and the loader --------------------------------------------

def test_only_a_title_with_a_travel_grid_has_the_window_addresses():
    pool = c64.MACHINES["pool-of-radiance"]
    assert (pool.resident_window_base, pool.travel_heading_base) == (0x8C00, 0x033D)
    for machine in c64.MACHINES.values():
        has = machine.title.travel_grid
        assert (machine.resident_window_base is not None) == bool(has)
        assert (machine.travel_heading_base is not None) == bool(has)


def test_load_world_is_none_without_disks(tmp_path):
    from automap.maps import load_world
    from goldbox import c64_port
    assert load_world(str(tmp_path), c64_port.POOL_OF_RADIANCE) is None
    assert load_world(None, c64_port.POOL_OF_RADIANCE) is None
    assert load_world(str(tmp_path), None) is None


# -- the file is not lost -----------------------------------------------------

def _write_file(state, payload):
    path = state.wilderness_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_a_state_that_never_loaded_the_file_does_not_overwrite_it(on):
    state = AutomapState()
    path = _write_file(state, {"seen": [[1, 2, 0, 5]]})
    state.save_wilderness()
    assert json.loads(path.read_text()) == {"seen": [[1, 2, 0, 5]]}


def test_recorded_squares_are_written(on):
    state = AutomapState()
    state.wilderness[(3, 4)] = (0, 7)
    state.save_wilderness()
    assert json.loads(state.wilderness_path().read_text())["seen"] == [[3, 4, 0, 7]]


def test_an_explicit_clear_writes_the_file_empty(on):
    state = AutomapState()
    path = _write_file(state, {"seen": [[1, 2, 0, 5]]})
    state.save_wilderness(clear=True)
    assert json.loads(path.read_text()) == {"seen": []}


@pytest.mark.parametrize("payload", [[], "x", {"seen": 3}, {"seen": [[1, 2]]},
                                     {"seen": [[1, 2, "a", 4]]}, 5])
def test_a_corrupt_file_loads_as_empty(on, payload):
    state = AutomapState()
    _write_file(state, payload)
    state.load_wilderness()
    assert state.wilderness == {}


def test_a_bad_row_is_skipped_and_the_good_ones_kept(on):
    state = AutomapState()
    _write_file(state, {"seen": [[1, 2], [3, 4, 1, 9]]})
    state.load_wilderness()
    assert state.wilderness == {(3, 4): (1, 9)}


def test_returning_to_the_old_square_drops_the_hold(on):
    mapper, _ = mapper_for(
        [out(8, 20), out(3, 20), out(8, 20), out(3, 20)], _window(1))
    mapper.poll()
    mapper.poll()
    assert mapper._outdoor_pending == (3, 20)
    mapper.poll()
    assert mapper._outdoor_pending is None
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (8, 20)
