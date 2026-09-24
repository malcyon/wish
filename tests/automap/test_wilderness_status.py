"""The status line outdoors names the region, behind
`WISH_EXPERIMENTAL_WILDERNESS_MAP`. Synthetic windows, no disks, no emulator."""

import pytest
from support.automapwindow import make_window

from automap import c64
from automap.state import WILDERNESS_ENV
from automap.target import Fix, ReplayTarget
from goldbox.world import GRID_SIZE, MIN_FILE_SIZE, Window, World

BASE = c64.RESIDENT_WINDOW


def _grid(seed: int) -> bytes:
    return bytes((i * (seed + 3) + seed) % 100 for i in range(GRID_SIZE))


def _world() -> World:
    return World(tuple(Window(_grid(i) + bytes(MIN_FILE_SIZE - GRID_SIZE))
                       for i in range(3)))


class Target(ReplayTarget):
    def __init__(self, fixes, block):
        super().__init__(fixes)
        self.block = block

    def read(self, addr, length):
        return self.block if addr == BASE else bytes(length)


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _status(app, tmp_path, monkeypatch, block, flag="1"):
    if flag is None:
        monkeypatch.delenv(WILDERNESS_ENV, raising=False)
    else:
        monkeypatch.setenv(WILDERNESS_ENV, flag)
    fix = Fix(8, 27, None, "status", 1000, outdoors=True)
    win = make_window(app, tmp_path, monkeypatch, Target([fix], block))
    win.mapper.use_world(_world())
    win.mapper.poll()
    win._refresh()
    return win.status_text()


@pytest.mark.parametrize("window, region", [
    (0, "West of Phlan"), (1, "Stojanow Valley"), (2, "East of Phlan")])
def test_the_status_line_names_the_region_and_the_local_square(
        app, tmp_path, monkeypatch, window, region):
    line = _status(app, tmp_path, monkeypatch, _grid(window))
    assert line == f"Outdoors  (8, 27)  {region}   [status]"


def test_an_unidentified_block_keeps_the_old_line(app, tmp_path, monkeypatch):
    assert (_status(app, tmp_path, monkeypatch, bytes(GRID_SIZE))
            == "Outdoors, no map   [status]")


@pytest.mark.parametrize("flag", [None, "0", "off", ""])
def test_with_the_flag_off_the_old_line_stays(app, tmp_path, monkeypatch, flag):
    assert (_status(app, tmp_path, monkeypatch, _grid(1), flag)
            == "Outdoors, no map   [status]")
