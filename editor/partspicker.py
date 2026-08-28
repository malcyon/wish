"""Choose an icon the way the game's own ICON menu does: a weapon and a head.

The old picker offered every glyph in the charset for each of 18 cells. That is
about 10^43 icons, of which some thousands are ones the game can make and the
rest are nonsense -- and it was possible to build a figure with two heads and no
legs and have the editor call it fine.

`goldbox/iconparts.py` carries the real model, read out of `SPELLE64`/`SPELLN64`.
This is the dialog over it: two lists, each entry rendered as the icon you would
end up with, so you pick a result rather than a number.

The SIZE control is here for the same reason the game has it, and with the same
consequence: it swaps which pair of tables is offered, is never written back to
the record, and so an icon may legally end up mixing a large body with a small
head. HOGARTH's does.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QListWidget,
    QListWidgetItem,
)

from goldbox.iconparts import IconParts
from goldbox.icons import PIXELS_WIDE, POSE_ROWS, POSES, Icon, icon_pixels

from .palette import colour
from .ui_partspicker import Ui_PartsPicker

# Four rather than three: the ask was a quarter bigger, and 3.75 is not a whole
# number of screen pixels per source pixel. At a fractional zoom `scaled` gives
# some source rows four pixels and some three, which on a 24-row sprite is
# visible as banding. A third bigger and clean beats a quarter bigger and ragged.
PREVIEW_ZOOM = 4
# The rows were drawn at the preview's own zoom and came out half the height of
# the thing being chosen: a pose is 24 source rows, so zoom 2 is a 48-pixel
# figure, and picking a helmet out of one is guesswork. The list is where the
# choosing happens, so it gets the larger zoom.
LIST_ZOOM = 4

#: Choices visible without scrolling. The lists are the dialog.
VISIBLE_ROWS = 5
# Source pixels, not screen pixels: one pose is 12 across, two poses 24. The
# multicolour doubling happens in the scale at the end. Conflating the two put
# each pose in the left half of a 48-wide image and left the rest black.
SOURCE_WIDE = PIXELS_WIDE * POSES
FRAME_HIGH = POSE_ROWS * 8
FRAME_WIDE = SOURCE_WIDE * 2                    # what it measures on screen


def preview(shape: bytes, colours: bytes, charset: bytes,
            zoom: int = PREVIEW_ZOOM) -> QImage:
    """One icon at an integer zoom, poses side by side, as the editor draws it."""
    pixels = icon_pixels(Icon(bytes(shape) + bytes(colours)), charset)
    img = QImage(SOURCE_WIDE, FRAME_HIGH, QImage.Format.Format_RGB32)
    img.fill(0)
    for y, row in enumerate(pixels):
        pose, into = divmod(y, FRAME_HIGH)
        for x, index in enumerate(row):
            img.setPixelColor(pose * PIXELS_WIDE + x, into, colour(index))
    return img.scaled(FRAME_WIDE * zoom, FRAME_HIGH * zoom,
                      Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.FastTransformation)


class PartsPicker(QDialog):
    """Pick a weapon and a head; the result is `shape`."""

    def __init__(self, parts: IconParts, charset: bytes, shape: bytes,
                 colours: bytes, size: str = "small", parent=None):
        super().__init__(parent)
        self.ui = Ui_PartsPicker()
        self.ui.setupUi(self)
        self.parts = parts
        self.charset = charset
        self.shape = bytes(shape)
        self.colours = bytes(colours)
        self.size = size

        self.preview = self.ui.preview

        self.size_box = self.ui.size_box
        self.size_box.setCurrentText(size)
        self.size_box.currentTextChanged.connect(self._size_changed)

        self.weapons = self.ui.weapons
        self.heads = self.ui.heads
        self._setup_list(self.weapons)
        self._setup_list(self.heads)
        self.weapons.currentRowChanged.connect(
            lambda row: self._chose("weapon", row))
        self.heads.currentRowChanged.connect(
            lambda row: self._chose("head", row))

        self.buttons = self.ui.buttons

        self._fill()
        self._open_tall()

    def _open_tall(self) -> None:
        """Open showing several choices, not one.

        The dialog had no size of its own, so the layout asked for the minimum
        that fits -- about a row and a half once the rows grew to the size of
        the icon being chosen. Height is what matters here: the lists are the
        dialog, and a picker you have to scroll to see two options in is the
        thing being complained about.

        Clamped to the screen with `QGuiApplication` rather than the
        project's own `clamp_to_screen`: that helper lives in the live-map
        package, and `tests/test_wish.py` greps this one for its name to keep
        the editor free of anything that could reach an emulator.
        """
        rows = self.weapons.sizeHintForRow(0) if self.weapons.count() else 104
        wanted = QSize(max(self.sizeHint().width(), FRAME_WIDE * LIST_ZOOM * 2 + 140),
                       rows * VISIBLE_ROWS + 190)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry()
            wanted = QSize(min(wanted.width(), room.width() - 80),
                            min(wanted.height(), room.height() - 80))
        self.resize(wanted)

    # -- building --------------------------------------------------------

    def _setup_list(self, view: QListWidget) -> None:
        view.setIconSize(QSize(FRAME_WIDE * LIST_ZOOM, FRAME_HIGH * LIST_ZOOM))
        view.setUniformItemSizes(True)

    def _fill(self) -> None:
        """Render every option as the icon it would produce from here."""
        for kind, view in (("weapon", self.weapons), ("head", self.heads)):
            blocked = view.blockSignals(True)
            view.clear()
            for option in range(self.parts.count(self.size, kind)):
                made = self.parts.apply(self.shape, self.size, kind, option)
                row = QListWidgetItem(str(option))
                row.setIcon(QIcon(QPixmap.fromImage(
                    preview(made, self.colours, self.charset, LIST_ZOOM))))
                view.addItem(row)
            view.blockSignals(blocked)
        self._show()

    def _show(self) -> None:
        self.preview.setPixmap(QPixmap.fromImage(
            preview(self.shape, self.colours, self.charset)))

    # -- choosing --------------------------------------------------------

    def _chose(self, kind: str, option: int) -> None:
        if option < 0:
            return
        self.shape = self.parts.apply(self.shape, self.size, kind, option)
        # Colours follow the parts: a new glyph in a cell takes its class's
        # colour, which is what the game does and what keeps the result legal.
        per_class = self.parts.part_colours(self.colours, self.shape)
        self.colours = self.parts.colours_for(self.shape, per_class,
                                              self.colours)
        self._fill()

    def _size_changed(self, name: str) -> None:
        self.size = name
        self._fill()
