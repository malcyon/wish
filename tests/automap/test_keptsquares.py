"""The squares a party has explored survive a Wish that ends without closing.

A player whose Wish crashes, or whose Wish is killed, never reaches the
window's close, which is where the notes file used to be written. Reopening
Wish then showed only the squares it could see from where the party stood.
Each test maps some squares through the real window, drops that window without
calling `shutdown` or `closeEvent`, opens a second window on the same title
and area, and checks the first window's squares are drawn.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from gamedata import synthetic_geo

from automap import c64
from automap.area import RESIDENT_GEO
from automap.state import Automapper
from automap.target import Fix, MemoryTarget, ReplayTarget
from goldbox.areas import POOL_OF_RADIANCE
from goldbox.geo import Geo

GEO = Geo(synthetic_geo())


class AmigaLike(ReplayTarget):
    """A target that answers `fix()` itself and is not a C64's memory, as
    `AmigaTarget` does, carrying the map at the resident address so the
    title check agrees."""

    c64_memory = False


def amiga_walking(*squares: tuple[int, int]) -> AmigaLike:
    fixes = [Fix(x, y, 0, "status", 600 + n) for n, (x, y) in enumerate(squares)]
    return AmigaLike(fixes, {RESIDENT_GEO: GEO.to_bytes()})


def screen_codes(text: str) -> bytes:
    """Text as the C64 stores it: A-Z are 1-26, punctuation is its own code."""
    return bytes((ord(c) - 64) if "A" <= c <= "Z" else ord(c) for c in text)


def c64_at(x: int, y: int) -> MemoryTarget:
    """A C64 with the game's status line on screen at `$CC00` saying the
    party is at `(x, y)` facing north, and the map resident at `$0400`, so
    the area is named from memory as it is in a real session."""
    row = screen_codes(f"N 16:48  {x},{y}".ljust(40))
    return MemoryTarget({0xD011: bytes([0x1B]), 0xD018: bytes([0x30]),
                         0xDD00: bytes([0x00]), 0xCC00 + 14 * 40: row,
                         c64.DEFAULT.live_position: bytes((x, y, 0)),
                         0x49E6: bytes([1]),
                         RESIDENT_GEO: GEO.to_bytes()})


def open_window(target, area: str | None, ticks: int):
    """The automapper page over `target`, polled `ticks` times. Returns the
    page and its host, which must stay referenced while the page is used."""
    from PyQt6.QtWidgets import QApplication, QMainWindow
    QApplication.instance() or QApplication([])

    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    mapper = Automapper(target, {"GEO00": GEO}, area=area,
                        title=POOL_OF_RADIANCE)
    page = AutomapBinding(root, mapper)
    for _ in range(ticks):
        page.tick()
    return page, root


def killed(page) -> None:
    """End the page the way a crash or `Stop-Process -Force` does: nothing
    of the close path runs. The timer is stopped only so the dropped page
    cannot poll again inside the test."""
    page.timer.stop()


def test_an_amiga_partys_squares_survive_a_killed_wish():
    """Wish restarted over a running game under WinUAE: the party is shown
    where it stands, and the squares it saw before the restart are still drawn."""
    page, _root = open_window(
        amiga_walking((2, 2), (2, 3), (3, 3), (4, 3), (4, 4)), "GEO00", 7)
    before = set(page.state.exploration.seen)
    assert {(2, 2), (4, 4)} <= before
    killed(page)

    again, _root2 = open_window(amiga_walking((12, 12)), "GEO00", 2)
    assert (again.state.x, again.state.y) == (12, 12)
    assert before <= again.state.exploration.seen


def test_a_c64_partys_squares_survive_a_killed_wish():
    """The same through the C64 path: the area named from the resident map,
    the position read from the status line."""
    page, _root = open_window(c64_at(3, 4), None, 12)
    assert page.state.area == "GEO00"
    before = set(page.state.exploration.seen)
    assert (3, 4) in before
    killed(page)

    again, _root2 = open_window(c64_at(12, 12), None, 12)
    assert again.state.area == "GEO00"
    assert (again.state.x, again.state.y) == (12, 12)
    assert before <= again.state.exploration.seen


def test_nothing_is_written_while_the_explored_set_does_not_grow():
    """A party standing still, or walking back over squares it has seen,
    writes nothing, so the file is written once per newly seen square at most
    and not on every poll."""
    page, _root = open_window(amiga_walking((2, 2)), "GEO00", 1)
    path = page.state.notes_path()
    path.write_text(json.dumps({"notes": {}, "seen": ["2,2"]}), encoding="utf-8")
    for _ in range(5):
        page.tick()
    assert json.loads(path.read_text(encoding="utf-8"))["seen"] == ["2,2"]


def test_a_write_that_fails_leaves_the_last_good_file():
    """The file is replaced whole: a write that dies part-way leaves the
    earlier file readable rather than a truncated one."""
    page, _root = open_window(amiga_walking((2, 2)), "GEO00", 1)
    path = page.state.notes_path()
    good = path.read_text(encoding="utf-8")

    class Boom(Exception):
        pass

    def half_written(self, text, encoding=None):
        open(self, "w", encoding=encoding).write(text[: len(text) // 2])
        raise Boom

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pathlib.Path, "write_text", half_written)
        with pytest.raises(Boom):
            page.state.save_notes()
    assert path.read_text(encoding="utf-8") == good
