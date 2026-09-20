"""Helpers `test_automap` shares with the test files that reuse them."""

import pathlib

from automap import live  # noqa: E402
from automap.state import Automapper


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


FIXTURES = pathlib.Path(__file__).parents[1] / "fixtures"


def captured() -> tuple[bytes, bytes]:
    """One real machine, recorded: BRUTUS alone in New Phlan.

    `SAVEDGAME0` is a verbatim image of $4900-$64FF and the roster is the first
    page of `SAVEDGAME1`, so these two fixtures are exactly the two reads the
    live view makes -- with the PRG load address stripped off each.
    """
    save0 = (FIXTURES / "savedgame0.bin").read_bytes()[2:]
    save1 = (FIXTURES / "savedgame1.bin").read_bytes()[2:]
    return save0, save1[:live.ROSTER_PAGE]


def make_window(app, tmp_path, monkeypatch, target, maps=None, area=None):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from PyQt6.QtWidgets import QMainWindow

    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    mapper = Automapper(target, maps or {}, area=area)
    return AutomapBinding(root, mapper)
