from __future__ import annotations

"""`tools/taskbaricon.py`: the comparison sheet is made by resizing the
artist's delivered files and by nothing else.

The first sheet drawn for `#351 (The Windows build shows no logo in About
and a black square on the taskbar, because the artist's SVGs are not in the
package)` switched off two elements of the artist's SVG in memory, cropped
his lettering with a viewBox and drew a pentagram of its own, and was
refused for it. What is checked here is the rule that replaced it: every
row is one delivered file, whole, rendered or scaled to a square -- so a
row's cell is pixel-identical to a fresh render of that file with nothing
done to it -- and the delivery on disk is unchanged afterwards.

The delivery lives outside the repository (`~/Downloads/wish_logo/`, or
`$WISH_LOGO_DELIVERY`), so every test that reads it skips where it is
absent, which is CI. The two tests that need no delivery run everywhere.
"""

import hashlib
import pathlib

import pytest

pytest.importorskip("PyQt6.QtSvg")

from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PyQt6.QtSvg import QSvgRenderer  # noqa: E402

from tools import taskbaricon  # noqa: E402

delivered = pytest.mark.skipif(
    not (taskbaricon.DELIVERY / "Marks").is_dir(),
    reason=f"the artist's delivery is not at {taskbaricon.DELIVERY}")


@pytest.fixture
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def _digests() -> dict[pathlib.Path, str]:
    return {p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(taskbaricon.DELIVERY.rglob("*")) if p.is_file()}


def test_the_rows_are_lettered_in_order_and_every_file_has_a_vector_row():
    rows = taskbaricon.rows()
    assert [r.letter for r in rows] == list("ABCDEFGHIJKL"[:len(rows)])
    vector = [(r.family, r.colourway) for r in rows if not r.raster]
    assert vector == taskbaricon.FILES


def test_a_raster_is_only_ever_scaled_down():
    """The smallest delivered PNG no smaller than the cell: 80 for the
    taskbar sizes, 500 for 256, never an upscale of a smaller one."""
    assert [taskbaricon.nearest_png(s) for s in taskbaricon.SIZES] == \
        [80, 80, 80, 80, 80, 500]


@delivered
@pytest.mark.parametrize("size", (24, 32))
def test_every_row_is_the_delivered_file_resized_and_nothing_else(app, size):
    """A row's cell equals a fresh render of the file it names, done here
    with no viewBox, no substitution and no element left out: the one way a
    crop or an edit in memory could get onto the sheet is by making the two
    differ."""
    for row in taskbaricon.rows():
        source = row.source(size)
        assert source.is_relative_to(taskbaricon.DELIVERY)
        got = row.draw(size)
        if row.raster:
            want = QImage(str(source)).convertToFormat(
                QImage.Format.Format_ARGB32_Premultiplied).scaled(
                    size, size, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
        else:
            renderer = QSvgRenderer(str(source))
            want = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
            want.fill(0)
            painter = QPainter(want)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
        assert got == want, f"row {row.letter} is not {source.name} resized"


@delivered
def test_the_ground_is_read_off_the_file(app):
    """The Color files bring an opaque near-black square; Black and White
    are line art on transparency. The caption says which, from the pixels."""
    grounds = {(r.colourway, r.raster): taskbaricon.ground(r.draw(48))
               for r in taskbaricon.rows() if r.family == "Marks"}
    for raster in (False, True):
        assert grounds[("Color", raster)].startswith("opaque")
        assert grounds[("Black", raster)].startswith("transparent")
        assert grounds[("White", raster)].startswith("transparent")


@delivered
def test_drawing_the_sheet_leaves_the_delivery_alone(app):
    before = _digests()
    image = taskbaricon.sheet()
    assert image.width() > 1500 and image.height() > 1500
    assert _digests() == before
