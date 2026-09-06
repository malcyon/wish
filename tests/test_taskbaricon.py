from __future__ import annotations

"""`tools/taskbaricon.py`: the comparison sheet draws, and draws off the
artist's files without changing them."""

import hashlib

import pytest

pytest.importorskip("PyQt6.QtSvg")

from PyQt6.QtGui import QGuiApplication  # noqa: E402

from tests.test_appicon import MARK_SHA256  # noqa: E402
from tools import taskbaricon  # noqa: E402


@pytest.fixture
def app():
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.mark.parametrize("letter", [o[0] for o in taskbaricon.OPTIONS])
@pytest.mark.parametrize("size", (16, 256))
def test_every_option_is_an_opaque_square_with_gold_on_it(app, letter, size):
    """What a taskbar needs: nothing showing through, and something to see."""
    draw = next(o[3] for o in taskbaricon.OPTIONS if o[0] == letter)
    image = draw(size)
    assert (image.width(), image.height()) == (size, size)
    pixels = [image.pixel(x, y) for y in range(size) for x in range(size)]
    assert all(p >> 24 == 255 for p in pixels), "not opaque"
    gold = [p for p in pixels if (p >> 16) & 255 > 90 and (p >> 8) & 255 > 70]
    assert gold, "nothing drawn on the ground"


def test_the_options_are_lettered_in_order():
    assert [o[0] for o in taskbaricon.OPTIONS] == list("ABCDEF")


def test_drawing_the_sheet_leaves_the_artists_file_alone(app):
    """Row B hands the renderer a document with the ring bitmaps left out;
    that document is in memory and the file on disk is the artist's."""
    taskbaricon.star_cropped(32)
    taskbaricon.monogram(32)
    digest = hashlib.sha256(taskbaricon.MARK.read_bytes()).hexdigest()
    assert digest == MARK_SHA256


def test_the_sheet_draws(app):
    image = taskbaricon.sheet()
    assert image.width() > 1500 and image.height() > 1500
