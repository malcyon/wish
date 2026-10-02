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

import pytest
from gamedata import synthetic_geo

from automap import c64, state
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


def test_a_write_that_fails_leaves_the_last_good_file(monkeypatch):
    """The file is replaced whole: a write that dies after the temporary file
    is written but before it is moved into place leaves the earlier file as
    it was, and the temporary file is removed."""
    page, _root = open_window(amiga_walking((2, 2)), "GEO00", 1)
    path = page.state.notes_path()
    good = path.read_text(encoding="utf-8")

    class Boom(Exception):
        pass

    def dies(_fd):
        raise Boom

    monkeypatch.setattr(state.os, "fsync", dies)
    page.state.exploration.seen.add((15, 15))
    with pytest.raises(Boom):
        page.state.save_notes()
    assert path.read_text(encoding="utf-8") == good
    assert not path.with_name(path.name + ".tmp").exists()


def test_the_file_is_flushed_to_the_disk_before_it_replaces_the_old_one(
        monkeypatch):
    """Without `fsync` a power cut after the rename can leave an empty file
    under the real name on some file systems."""
    order = []
    real_fsync, real_replace = state.os.fsync, state.os.replace
    monkeypatch.setattr(state.os, "fsync",
                        lambda fd: order.append("fsync") or real_fsync(fd))
    monkeypatch.setattr(state.os, "replace",
                        lambda a, b: order.append("replace") or real_replace(a, b))
    open_window(amiga_walking((2, 2)), "GEO00", 1)
    assert order == ["fsync", "replace"]


def test_a_save_that_keeps_failing_is_logged_once_until_one_succeeds(
        monkeypatch, caplog):
    """A notes file another program holds open fails every newly seen
    square on Windows. The log says so once, says when saving works again,
    and leaves no temporary file behind."""
    real_replace = state.os.replace
    blocked = [True]

    def replace(a, b):
        if blocked[0]:
            raise PermissionError(13, "The process cannot access the file")
        return real_replace(a, b)

    monkeypatch.setattr(state.os, "replace", replace)
    caplog.set_level("INFO", logger="wish.automap.state")
    # Each of these steps sees new squares on the synthetic map.
    page, _root = open_window(
        amiga_walking((2, 2), (2, 3), (2, 4), (2, 5), (2, 6)), "GEO00", 3)
    path = page.state.notes_path()
    assert not path.with_name(path.name + ".tmp").exists()
    blocked[0] = False
    page.tick()
    blocked[0] = True
    page.tick()

    warned = [r.getMessage() for r in caplog.records
              if r.name == "wish.automap.state"]
    assert [m.split(":")[0] for m in warned] == [
        "Could not save the explored squares",
        "The explored squares are being saved again",
        "Could not save the explored squares",
    ]


def test_the_flat_notes_migration_runs_once_per_area_not_once_per_square(
        monkeypatch):
    """`migrate_flat_notes` globs the whole data directory; saving each new
    square must not run it again while the party stays in one area."""
    calls = []
    real = state.migrate_flat_notes
    monkeypatch.setattr(state, "migrate_flat_notes",
                        lambda *a: calls.append(a) or real(*a))
    route = [(2, 2), (2, 3), (2, 4), (2, 5), (2, 6)]
    page, _root = open_window(amiga_walking(*route), "GEO00", len(route))
    assert len(page.state.exploration) > 40
    assert len(calls) == 1
