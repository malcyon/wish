"""The candidate icons of `docs/109-icon-choices.md`.

Kept out of `tests/test_automap.py` because the whole block is temporary: when
Donald picks from `work/reports/icon-sheet.png` the winners move into
`FONT_AWESOME` and `OURS`, the rest of `CANDIDATES` goes, and this file goes
with it.

What is worth testing about a drawing is small: that it parses, that it stays
in its box, and -- for the one icon whose whole argument is the hole -- that
the hole is still a hole once Qt has filled it.
"""

from __future__ import annotations

import pytest

from automap import icons

pytest.importorskip("PyQt6.QtGui")


def test_every_candidate_parses():
    """A hand-drawn path with a typo in it fails here rather than as a blank
    square on the sheet."""
    for name in icons.CANDIDATES:
        assert icons.commands(name), name


def test_no_candidate_leaves_the_640_box():
    """`render.py` places a note by its box, not by its ink: an icon that
    overhangs lands on a wall. See `test_a_note_never_lands_on_a_wall`."""
    for name in icons.CANDIDATES:
        x0, y0, x1, y1 = icons.extent(name)
        assert 0 <= x0 and 0 <= y0 and x1 <= icons.BOX and y1 <= icons.BOX, \
            f"{name} is {x0},{y0}..{x1},{y1}"


def test_no_candidate_shadows_an_icon_already_in_use():
    """`ICONS` merges the three dicts, so a repeated name would silently
    replace what the map draws today."""
    for name in icons.CANDIDATES:
        assert name not in icons.FONT_AWESOME, name
        assert name not in icons.OURS, name


def test_the_hood_keeps_its_face():
    """The hooded head is `location-dot`'s argument applied deliberately: one
    solid silhouette, one hole. Drawn at 13px the face must still be paper --
    odd-even fill, or a subpath wound the same way as the cowl, fills it in and
    leaves a bell."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    from automap.iconpaint import draw_icon

    image = QImage(13, 13, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, "hood", 0, 0, 13, QColor("black"))
    p.end()

    # The face sits a little above the middle; the shoulders below it are ink.
    face = QColor(image.pixel(6, 5)).lightness()
    shoulder = QColor(image.pixel(6, 10)).lightness()
    assert face > 200, f"the face filled in: lightness {face}"
    assert shoulder < 80, f"the shoulders are not ink: lightness {shoulder}"


def test_the_sheet_only_names_icons_that_exist():
    """`tools/iconsheet.py` is the deliverable; a renamed icon must break the
    build rather than the sheet."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parent.parent / "tools" \
        / "iconsheet.py"
    spec = importlib.util.spec_from_file_location("iconsheet", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    named = [name for _, items in module.SHEET for name, _, _ in items]
    assert named, "the sheet lists nothing"
    for name in named:
        assert name in icons.ICONS, name
