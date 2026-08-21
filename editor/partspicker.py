"""Choose an icon the way the game's own ICON menu does: a weapon and a head.

The old picker offered every glyph in the charset for each of 18 cells. That is
about 10^43 icons, of which some thousands are ones the game can make and the
rest are nonsense -- and it was possible to build a figure with two heads and no
legs and have the editor call it fine.

`por/iconparts.py` carries the real model, read out of `SPELLE64`/`SPELLN64`.
This is the dialog over it: two lists, each entry rendered as the icon you would
end up with, so you pick a result rather than a number.

The SIZE control is here for the same reason the game has it, and with the same
consequence: it swaps which pair of tables is offered, is never written back to
the record, and so an icon may legally end up mixing a large body with a small
head. HOGARTH's does.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from por.iconparts import IconParts
from por.icons import PIXELS_WIDE, POSE_ROWS, POSES, Icon, icon_pixels

from .palette import colour

PREVIEW_ZOOM = 3
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
        self.setWindowTitle("Choose an icon")
        self.parts = parts
        self.charset = charset
        self.shape = bytes(shape)
        self.colours = bytes(colours)
        self.size = size

        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.size_box = QComboBox(self)
        for name in ("small", "large"):
            self.size_box.addItem(name)
        self.size_box.setCurrentText(size)
        self.size_box.currentTextChanged.connect(self._size_changed)

        self.weapons = self._list()
        self.heads = self._list()
        self.weapons.currentRowChanged.connect(
            lambda row: self._chose("weapon", row))
        self.heads.currentRowChanged.connect(
            lambda row: self._chose("head", row))

        lists = QHBoxLayout()
        for label, view in (("Weapon", self.weapons), ("Head", self.heads)):
            column = QVBoxLayout()
            column.addWidget(QLabel(label, self))
            column.addWidget(view)
            holder = QWidget(self)
            holder.setLayout(column)
            lists.addWidget(holder)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        top = QHBoxLayout()
        top.addWidget(QLabel("Size", self))
        top.addWidget(self.size_box)
        top.addStretch(1)
        top.addWidget(self.preview)

        outer = QVBoxLayout(self)
        outer.addLayout(top)
        outer.addLayout(lists)
        outer.addWidget(buttons)
        self._fill()

    # -- building --------------------------------------------------------

    def _list(self) -> QListWidget:
        view = QListWidget(self)
        view.setIconSize(QSize(FRAME_WIDE * 2, FRAME_HIGH * 2))
        view.setUniformItemSizes(True)
        return view

    def _fill(self) -> None:
        """Render every option as the icon it would produce from here."""
        for kind, view in (("weapon", self.weapons), ("head", self.heads)):
            blocked = view.blockSignals(True)
            view.clear()
            for option in range(self.parts.count(self.size, kind)):
                made = self.parts.apply(self.shape, self.size, kind, option)
                row = QListWidgetItem(str(option))
                row.setIcon(QIcon(QPixmap.fromImage(
                    preview(made, self.colours, self.charset, 2))))
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
