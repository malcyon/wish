"""The combat-icon editor: real pixel art, and a sixteen-colour picker.

Promote a plain `QWidget` to this class in Qt Designer -- class `IconEditor`,
header `editor.iconwidget` -- and it can then be moved and resized on the form
like any other widget.

What it draws is the genuine article. An icon is 18 cells: **two 3x3 poses
stacked**, each cell a glyph from `CHARPIC00` in **multicolour** text mode, so a
cell row is four double-width pixels rather than eight. Three of the four
colours are shared and come from VIC registers the save does not hold; `COM.PREP`
sets them, and `por/icons.py` carries the values it uses.

Clicking a cell offers the sixteen C64 colours and nothing else, plus the
glyph picker. A general colour dialog would let you pick something the machine
cannot display.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QDialog, QMenu, QWidget

from por.icons import (
    CELL_COLS,
    CELLS,
    COMBAT_BORDER,
    PIXELS_WIDE,
    POSE_ROWS,
    POSES,
    Icon,
    icon_pixels,
)

from .palette import COLOURS, NAMES, colour
from .partspicker import PartsPicker

ZOOM = 6                    # pixel doubling on top of multicolour's own

# The two poses are drawn side by side rather than stacked. Stacked, the icon is
# 24 wide by 48 tall, and a widget that tall pushed the roster strip to 430
# pixels for a table needing 240 -- the shape fought the layout. Side by side it
# is 48 by 24, which is also the better read: you compare the poses at a glance.
FRAME_WIDE = PIXELS_WIDE * 2 * POSES     # multicolour doubling, then two poses
FRAME_HIGH = POSE_ROWS * 8


class IconEditor(QWidget):
    """Shows one character's combat icon and lets its colours be changed."""

    iconChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon: Icon | None = None
        self._charset: bytes = b""
        self._pixels: list[list[int]] = []
        self._parts = None
        self._size = "small"
        self.setMinimumSize(FRAME_WIDE * ZOOM, FRAME_HIGH * ZOOM)
        self.setMaximumWidth(FRAME_WIDE * ZOOM * 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- what to draw -----------------------------------------------------

    def set_icon(self, icon: Icon | None, charset: bytes = b"") -> None:
        self._icon = icon
        if charset:
            self._charset = charset
        self._rebuild()

    def _rebuild(self) -> None:
        if self._icon is not None and self._charset:
            self._pixels = icon_pixels(self._icon, self._charset)
        else:
            self._pixels = []
        self.update()

    @property
    def icon(self) -> Icon | None:
        return self._icon

    # -- geometry ---------------------------------------------------------

    def _geometry(self) -> tuple[int, int, int]:
        """`(scale, x0, y0)` -- an integer zoom, centred, aspect preserved.

        A multicolour pixel is two screen pixels wide, so the icon's natural
        shape is 24 by 48. Letting a form layout stretch it to fill smears the
        art; better to keep it square-pixelled and centre it.
        """
        if not self._pixels:
            return 1, 0, 0
        scale = max(1, min(self.width() // FRAME_WIDE,
                           self.height() // FRAME_HIGH))
        w, h = FRAME_WIDE * scale, FRAME_HIGH * scale
        return scale, (self.width() - w) // 2, (self.height() - h) // 2

    def _cell_at(self, px: float, py: float) -> int | None:
        if not self._pixels:
            return None
        scale, x0, y0 = self._geometry()
        x = int((px - x0) // (scale * 2)) // 4
        y = int((py - y0) // scale) // 8
        if 0 <= x < CELL_COLS * POSES and 0 <= y < POSE_ROWS:
            pose, column = divmod(x, CELL_COLS)
            return pose * CELL_COLS * POSE_ROWS + y * CELL_COLS + column
        return None

    # -- painting ---------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), colour(COMBAT_BORDER))
        if not self._pixels:
            p.setPen(QPen(QColor("#ffffff")))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "no icon" if self._icon is None else "no game disk")
            return

        scale, x0, y0 = self._geometry()
        for y, row in enumerate(self._pixels):
            # `icon_pixels` stacks the poses; move the lower one to the right.
            pose, into = divmod(y, FRAME_HIGH)
            for x, index in enumerate(row):
                p.fillRect(QRect(x0 + (pose * PIXELS_WIDE + x) * scale * 2,
                                 y0 + into * scale,
                                 scale * 2, scale), colour(index))

        # A hairline between the two poses, so it reads as two frames rather
        # than one tall figure.
        p.setPen(QPen(QColor(255, 255, 255, 70), 1, Qt.PenStyle.DashLine))
        mid = x0 + PIXELS_WIDE * 2 * scale
        p.drawLine(mid, y0, mid, y0 + FRAME_HIGH * scale)

    # -- editing ----------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        cell = self._cell_at(event.position().x(), event.position().y())
        if cell is None or self._icon is None:
            return
        menu = QMenu(self)
        # "Change the icon" replaces the old per-cell glyph pick. A cell is not
        # a thing the game lets you choose: the ICON menu offers a weapon and a
        # head, and picking screen codes cell by cell built figures with two
        # heads that no amount of playing could produce.
        whole = menu.addAction("Change the icon…")
        whole.setData(-1)
        menu.addSeparator()
        current = self._icon.colours[cell] & 0x0F
        for i, name in enumerate(NAMES):
            act = menu.addAction(f"{i:2d}  {name}")
            act.setCheckable(True)
            act.setChecked(i == current)
            pix = COLOURS[i]
            act.setData(i)
            act.setIconVisibleInMenu(True)
            act.setIcon(_swatch(pix))
        chosen = menu.exec(event.globalPosition().toPoint())
        if chosen is None:
            return
        if int(chosen.data()) < 0:
            self._pick_parts()
        else:
            self.set_cell_colour(cell, int(chosen.data()))

    def _pick_parts(self) -> None:
        """The whole icon, from the game's own two lists."""
        if not self._charset or self._parts is None or self._icon is None:
            return
        dialog = PartsPicker(self._parts, self._charset,
                             bytes(self._icon.shape),
                             bytes(self._icon.colours), self._size, self)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        self.set_shape(dialog.shape, dialog.colours)

    def set_parts(self, parts, size: str = "small") -> None:
        """Hand the widget the option tables. Without them the icon still
        draws; it just cannot be changed, which is the right failure when the
        character-creation disk is not to hand."""
        self._parts = parts
        self._size = size

    def set_shape(self, shape: bytes, colours: bytes) -> None:
        if self._icon is None:
            return
        self._icon = Icon(bytes(shape) + bytes(colours))
        self._rebuild()
        self.update()
        self.iconChanged.emit()

    def set_cell_glyph(self, cell: int, code: int) -> None:
        if self._icon is None or not 0 <= cell < CELLS:
            return
        raw = bytearray(self._icon.raw)
        if raw[cell] == code:
            return
        raw[cell] = code & 0xFF
        self._icon = Icon(bytes(raw))
        self._rebuild()
        self.iconChanged.emit()

    def set_cell_colour(self, cell: int, value: int) -> None:
        if self._icon is None or not 0 <= cell < CELLS:
            return
        raw = bytearray(self._icon.raw)
        if raw[CELLS + cell] == value:
            return
        raw[CELLS + cell] = value & 0x0F
        self._icon = Icon(bytes(raw))
        self._rebuild()
        self.iconChanged.emit()


def _swatch(colour_: QColor):
    from PyQt6.QtGui import QIcon, QPixmap
    pix = QPixmap(16, 16)
    pix.fill(colour_)
    return QIcon(pix)
