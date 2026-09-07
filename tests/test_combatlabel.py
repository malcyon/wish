from __future__ import annotations

"""The hit-point label on a combat square, fitted to the cell that is
actually painted -- `#347 (The combat map's hit points are drawn at one
fixed size however small or large the square is painted)`.

`CombatCanvas._draw` used to size the label's font from `self.cell`, the
size the fight *would like* (`combat.cell_for`, capped at 30 and the same
for every fight seen), and only `paintEvent`'s grid lines and every other
primitive used `drawn_cell`, the size the widget actually has room for. A
narrow window drew a two-digit number wider than its 12px square; a wide
one left the number a 10pt speck in a 66px square. `CombatCanvas._label_font`
is what replaces the fixed fraction: a `QFontMetricsF` search for the
largest bold sans that keeps a given piece of text inside a given cell.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from gamedata import synthetic_arena
from PyQt6.QtGui import QFontMetricsF

from automap import combat, window
from automap.render import Label
from automap.target import MemoryTarget
from automap.window import CombatCanvas

#: Every cell size the map is ever asked to draw: the floor, `cell_for`'s
#: own range (12-30), and past it to where a maximised window lands --
#: 66 is the 1400x900 measurement quoted on the issue.
CELLS = (combat.CELL_MIN, 13, 16, 20, combat.CELL_MAX, 45, 66, 100)

#: The narrowest and widest hit-point text this map draws: one digit
#: against three, both cited on the issue (`7` against `118`), plus the
#: "no reading" case the tooltip's own `hp_text` can hand it.
TEXTS = ("7", "11", "118", "?")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def battle():
    return combat.read_battle(MemoryTarget(synthetic_arena()))


# --- the fit itself -----------------------------------------------------

@pytest.mark.parametrize("cell", CELLS)
@pytest.mark.parametrize("text", TEXTS)
def test_the_label_fits_inside_its_own_square(app, cell, text):
    """The outcome a player cares about: whatever the cell size, the chosen
    font's own measurement of the text -- not a guess about it -- lands
    inside the square it is drawn in."""
    font = CombatCanvas._label_font(text, cell)
    fm = QFontMetricsF(font)
    assert fm.horizontalAdvance(text) <= cell
    assert fm.capHeight() <= cell


@pytest.mark.parametrize("cell", CELLS)
def test_the_widest_value_fits_wherever_the_narrow_one_did(app, cell):
    """`7` and `118` are different widths at the same cell -- a font picked
    for one is not proof it holds for the other, so both are asserted at
    every cell rather than trusting whichever text happened to be on
    screen when this was written."""
    for text in ("7", "118"):
        font = CombatCanvas._label_font(text, cell)
        fm = QFontMetricsF(font)
        assert fm.horizontalAdvance(text) <= cell, (cell, text)
        assert fm.capHeight() <= cell, (cell, text)


# --- scaling with the cell, not fixed and not jumping --------------------

def test_the_font_grows_with_the_cell_and_never_shrinks_as_it_grows(app):
    """The bug this replaces: a fixed point size that ignored the cell
    altogether. The fitted size must climb as the cell does, and never fall
    back down -- a player growing the window should never see the number
    get smaller."""
    sizes = [CombatCanvas._label_font("11", cell).pixelSize() for cell in CELLS]
    assert sizes == sorted(sizes)
    assert sizes[0] < sizes[-1], "a canvas 8x the width draws a bigger number"


def test_the_font_is_not_the_same_fixed_size_at_every_cell(app):
    """Pins the actual defect: the old code chose its font from `self.cell`,
    the fight's preferred size, so every cell from 12px to 200px drew the
    same points. Fails against that code and passes once the font comes
    from the cell actually painted."""
    small = CombatCanvas._label_font("11", combat.CELL_MIN).pixelSize()
    large = CombatCanvas._label_font("11", 100).pixelSize()
    assert small != large


# --- the floor: small, not vanished ---------------------------------------

@pytest.mark.parametrize("text", TEXTS)
def test_at_the_smallest_cell_the_number_is_not_drawn_at_zero_or_one_pixel(
        app, text):
    """`CELL_MIN` is the smallest square the map ever draws. The label there
    is small, but a font of 0px or 1px is not a digit any more -- assert the
    floor `_label_font` itself defines, `MIN_LABEL_PIXELS`, rather than a
    number read off one run."""
    font = CombatCanvas._label_font(text, combat.CELL_MIN)
    assert font.pixelSize() >= CombatCanvas.MIN_LABEL_PIXELS
    assert font.pixelSize() > 1


# --- the real pipeline: a captured fight, not just the pure function -----

def test_the_floor_is_measured_even_when_nothing_fits(app, monkeypatch):
    """A code review of `#347 (The combat map's hit points are drawn at one
    fixed size however small or large the square is painted)` found that the
    search fell through to `MIN_LABEL_PIXELS` without ever measuring it --
    on this machine's DejaVu Sans the floor happens to fit, but a "sans"
    that resolves to something wider would overflow the square with nobody
    having checked. Force every candidate size to fail, including the floor,
    and confirm `_label_font` still measures it (rather than skipping
    straight to an unmeasured font) and returns it deliberately."""
    class _NeverFits:
        def __init__(self, font):
            pass

        def capHeight(self):
            return 1000.0

        def horizontalAdvance(self, text):
            return 1000.0

    calls = []
    real_init = _NeverFits.__init__

    def recording_init(self, font):
        calls.append(font.pixelSize())
        real_init(self, font)

    _NeverFits.__init__ = recording_init
    monkeypatch.setattr(window, "QFontMetricsF", _NeverFits)

    font = CombatCanvas._label_font("118", combat.CELL_MIN)

    assert font.pixelSize() == CombatCanvas.MIN_LABEL_PIXELS
    assert CombatCanvas.MIN_LABEL_PIXELS in calls, (
        "the floor size must be measured, not returned unmeasured")


def test_a_captured_fights_labels_fit_at_the_floor_and_when_grown(app):
    """Drives `CombatCanvas` the way the window does: `show_battle`, resize,
    read the primitives `paintEvent` would hand `_draw`, and check every
    `Label` it yields fits the cell the canvas actually settled on."""
    canvas = CombatCanvas()
    canvas.show_battle(battle())

    canvas.resize(canvas.minimumSize())
    _check_labels_fit(canvas)

    canvas.resize(1400, 900)
    _check_labels_fit(canvas)


def _check_labels_fit(canvas: CombatCanvas) -> None:
    cell = canvas.drawn_cell
    prims = combat.battlefield(canvas.battle, canvas.box, cell, combat.MARGIN)
    labels = [p for p in prims if isinstance(p, Label)]
    assert labels, "the captured fight draws at least one hit-point label"
    for label in labels:
        font = CombatCanvas._label_font(label.text, cell)
        fm = QFontMetricsF(font)
        assert fm.horizontalAdvance(label.text) <= cell, (cell, label.text)
        assert fm.capHeight() <= cell, (cell, label.text)
