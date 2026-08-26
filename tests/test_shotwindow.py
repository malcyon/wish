"""`tools/shotwindow.py` photographs the window, and the numbers it reports.

The picture is not what is asserted on. A rendered image is not byte-identical
between two machines -- a different font, a different Qt, a different
antialiasing -- and this project has been bitten by exactly that more than once.
What is stable is the shape of what comes out and the numbers the tool measures,
so that is what is here:

* it writes a PNG, and the PNG is the window plus the caption strip;
* the floor it reports is the same number at two UI fonts, because #71 made the
  window's minimum width a constant rather than a font metric -- if this ever
  differs, either the header has gone back to measuring a string or the tool
  has stopped measuring the window in front of it;
* it puts the application's font back.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from tools import shotwindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def save(tmp_path):
    from gamedata import synthetic_save

    return str(synthetic_save(tmp_path))


def test_it_writes_a_picture_of_the_window(app, tmp_path, save, capsys):
    out = tmp_path / "shot.png"
    assert shotwindow.main(["shotwindow", "--save", save, str(out)]) == 0
    assert out.exists() and out.stat().st_size > 0

    image = QImage(str(out))
    assert not image.isNull(), "what it wrote is not an image"
    # The caption strip sits above the grab, so the picture is exactly that
    # much taller than the window it drew. No pixel is looked at.
    report = capsys.readouterr().out
    width, height = [int(n) for n in report.split("drawn ")[1].split()[0]
                     .split("x")]
    assert (image.width(), image.height()) == (width,
                                               height + shotwindow.CAPTION_H)


def test_the_floor_it_reports_does_not_follow_the_ui_font(app, save):
    """#71's guarantee, measured through the tool.

    948 at every font this machine can be made to draw is what
    `tests/test_mapscale.py` records; the assertion is that the two agree with
    each other, not that either is 948, because the number is a Linux number
    and the equality is the finding.
    """
    _, base, _ = shotwindow.shoot(app, save, extra=0)
    _, big, _ = shotwindow.shoot(app, save, extra=6)
    assert base.width() == big.width(), (
        f"the floor grew with the font: {base.width()} then {big.width()}")


def test_a_window_narrower_than_the_target_is_not_marked(app, save):
    """The line is drawn where it means something and nowhere else.

    Two captions of the same picture, one with the target above the width and
    one below it, differ -- which is the mark. A colour is counted rather than
    a pixel position asserted, because where the line lands is a rendering
    detail and whether it was drawn at all is not.
    """
    image, _, drawn = shotwindow.shoot(app, save, extra=0)
    row = 2                                     # inside the caption strip

    def marks(target):
        painted = shotwindow.caption(image, "x", target)
        return sum(painted.pixelColor(x, row) == shotwindow.MARK
                   for x in range(painted.width()))

    assert marks(drawn[0] + 100) == 0, "marked a window that fits"
    assert marks(drawn[0] // 2) > 0, "did not mark a window that does not fit"


def test_it_puts_the_applications_font_back(app, save):
    before = app.font().pointSizeF()
    shotwindow.shoot(app, save, extra=6)
    assert app.font().pointSizeF() == before


def test_the_tab_names_it_offers_are_the_windows_own(app):
    """Getting the tab wrong wastes a run: the window opens on the automapper
    and every layout question is in the editor."""
    from wish.window import EDITOR_TAB, MAP_TAB

    assert shotwindow.TABS == {"editor": EDITOR_TAB, "map": MAP_TAB}


def test_an_unreadable_save_is_reported_rather_than_waited_on(app, tmp_path,
                                                              capsys):
    """The failure this tool cannot afford: a dialog nobody can dismiss.

    `EditorWindow.load` reports an unreadable save with `QMessageBox.critical`,
    which is a blocking `exec()`. Offscreen there is no one to click it, so
    `--save` on a file that is not a save hung until it was killed -- measured
    at eight seconds and exit 124, with no output at all. It is the same fault
    `shoot`'s teardown already avoided for the unsaved-changes box, in a place
    nobody had looked.

    Now every dialog is answered, said out loud, and counted: the picture is
    still written, because it is evidence of what the window did, and the exit
    code is 2, because the run is not a success.
    """
    bad = tmp_path / "not-a-save.d64"
    bad.write_bytes(b"this is not a disk image")
    out = tmp_path / "bad.png"

    code = shotwindow.main(["shotwindow", "--save", str(bad), str(out)])

    assert code == 2, "an unreadable save reported success"
    assert out.exists(), "the picture is evidence and should still be written"
    assert shotwindow.SUPPRESSED, "the dialog was not recorded"
    assert "Cannot open" in " ".join(shotwindow.SUPPRESSED)


def test_the_map_tab_is_given_its_maps(app, save, monkeypatch):
    """`maps={}` is not `maps=None`, and only the second loads anything.

    `WishWindow` does `maps if maps is not None else load_maps(...)`, so an
    empty dict is taken as "here are your maps, there are none of them" and
    every `--tab map` picture came out an empty automapper -- including the one
    in this tool's own usage example.
    """
    seen = {}
    real = shotwindow.WishWindow

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(shotwindow, "WishWindow", spy)
    shotwindow.shoot(app, str(save), extra=0, width=None, height=None,
                     tab=shotwindow.TABS["map"])
    assert seen["maps"] is None, "the map tab was handed an empty map set"

    seen.clear()
    shotwindow.shoot(app, str(save), extra=0, width=None, height=None,
                     tab=shotwindow.TABS["editor"])
    assert seen["maps"] == {}, "the editor tab paid for a map load it never draws"


def test_the_session_does_not_outlive_the_shot(app, save, monkeypatch):
    """Every shot used to leave a 1000ms timer ticking for the process's life.

    `WishWindow.closeEvent` is the only thing that stops the session, and this
    tool deliberately never calls `close()` -- so nothing did. Harmless on the
    editor tab, where the reader is None and `poll` no-ops; not harmless on
    `--tab map`, where each leaked timer goes on calling `attach()` once a
    second, forever, and this tool takes several shots per run.
    """
    made = []
    real = shotwindow.Session

    def spy(*args, **kwargs):
        s = real(*args, **kwargs)
        made.append(s)
        return s

    monkeypatch.setattr(shotwindow, "Session", spy)
    shotwindow.shoot(app, str(save), extra=0, width=None, height=None,
                     tab=shotwindow.TABS["editor"])

    assert made, "no session was built"
    assert not made[0].timer.isActive(), "the session is still polling"

