"""Reading the travel grid's window.
No disks and no emulator: the windows are synthetic and `ReplayTarget` answers
`$8C00`."""

import pytest

from automap import c64
from automap.state import Automapper
from automap.target import Fix, ReplayTarget
from goldbox.world import GRID_SIZE, MIN_FILE_SIZE, Window, World

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
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


def mapper_for(fixes, block, world=None):
    target = Target(fixes, block)
    mapper = Automapper(target)
    mapper.use_world(world if world is not None else _world())
    return mapper, target


def out(x, y, source="status"):
    return Fix(x, y, None, source, 1000, outdoors=True)


def test_one_tick_names_the_window(on):
    mapper, _ = mapper_for([out(8, 20)], _window(1))
    assert mapper.poll() is True
    assert mapper.state.window == 1


def test_a_block_that_names_no_window_leaves_the_window(on):
    mapper, _ = mapper_for([out(8, 20)], bytes(GRID_SIZE))
    mapper.state.window = 2
    mapper.poll()
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
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (3, 20)


def test_a_jump_into_a_new_window_is_not_held(on):
    mapper, target = mapper_for([out(15, 27), out(3, 27)], _window(1))
    mapper.poll()
    target.block = _window(2)
    mapper.poll()
    assert mapper.state.window == 2


def test_a_camped_party_is_believed_when_the_window_identifies(on):
    mapper, _ = mapper_for([out(8, 20, "memory")], _window(1))
    assert mapper.poll() is True
    assert mapper.state.outdoors


def test_a_camped_party_over_a_zero_page_is_still_blocked(on):
    mapper, _ = mapper_for([out(8, 20, "memory")], bytes(GRID_SIZE))
    assert mapper.poll() is False
    assert not mapper.state.outdoors


def test_a_target_that_is_not_a_c64_is_never_read(on):
    mapper, target = mapper_for([out(8, 20)], _window(1))
    target.c64_memory = False
    mapper.poll()
    assert target.reads == []


def test_with_no_world_nothing_is_read(on):
    target = Target([out(8, 20, "memory")], _window(1))
    mapper = Automapper(target)
    mapper.use_world(None)
    assert mapper.poll() is False           # no proof without a world
    assert target.reads == []


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


def test_load_world_skips_an_empty_image_instead_of_raising(tmp_path):
    from automap.maps import load_world
    from goldbox import c64_port
    game = c64_port.POOL_OF_RADIANCE
    (tmp_path / "POOL1.d64").write_bytes(b"")
    assert load_world(str(tmp_path), game) is None


def test_load_world_skips_an_image_whose_directory_is_broken(tmp_path):
    from automap.maps import load_world
    from goldbox import c64_port
    from goldbox.d64 import D64
    image = bytearray(D64.blank().data)
    image[91648] = 99                       # track 18 sector 1 links to 99
    (tmp_path / "POOL1.d64").write_bytes(bytes(image))
    assert load_world(str(tmp_path), c64_port.POOL_OF_RADIANCE) is None


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


def test_load_world_with_one_blank_amiga_disk_is_none(tmp_path):
    from automap.maps import amiga_images, load_world
    from goldbox import c64_port
    from goldbox.amiga_adf import AmigaDisk
    AmigaDisk.blank("pooldata").save(tmp_path / "blank.adf")
    # The blank disk is the title's own, so the loader opens it and finds no program.
    assert len(amiga_images(str(tmp_path), c64_port.POOL_OF_RADIANCE)) == 1
    assert load_world(str(tmp_path), c64_port.POOL_OF_RADIANCE) is None


def test_load_world_reads_the_amiga_disks_when_no_c64_disk_is_there(tmp_path):
    from automap.maps import load_world
    from goldbox import c64_port
    from goldbox.amiga_world import AmigaWorld
    from goldbox.world import World
    sources = _players_amiga_disks()
    for n, disk in enumerate(sources):
        disk.save(tmp_path / f"disk{n}.adf")
    assert isinstance(load_world(str(tmp_path), c64_port.POOL_OF_RADIANCE), AmigaWorld)
    assert not isinstance(load_world(str(tmp_path), c64_port.POOL_OF_RADIANCE), World)


def _players_amiga_disks():
    import pytest

    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves
    found = {}
    for _label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
        except ValueError:
            continue
        if disk.volume_name.lower() in ("poolgame", "pooldata"):
            found.setdefault(disk.volume_name.lower(), disk)
    if len(found) < 2:
        pytest.skip("needs the Amiga Pool of Radiance disks")
    return list(found.values())
