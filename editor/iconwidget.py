"""The combat-icon editor: real pixel art, and a sixteen-colour picker.

Promote a plain `QWidget` to this class in Qt Designer -- class `IconEditor`,
header `editor.iconwidget` -- and it can then be moved and resized on the form
like any other widget.

What it draws is the genuine article. An icon is 18 cells: **two 3x3 poses
stacked**, each cell a glyph from `CHARPIC00` in **multicolour** text mode, so a
cell row is four double-width pixels rather than eight. Three of the four
colours are shared and come from VIC registers the save does not hold; `COM.PREP`
sets them, and `goldbox/icons.py` carries the values it uses.

Clicking a cell offers the sixteen C64 colours and nothing else, plus the
glyph picker. A general colour dialog would let you pick something the machine
cannot display.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from goldbox.iconparts import PART_CLASSES
from goldbox.icons import (
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

ZOOM = 4                    # 33% increase (UI scaled) over native

# The two poses are drawn side by side rather than stacked. Stacked, the icon is
# 24 wide by 48 tall, and a widget that tall pushed the roster strip to 430
# pixels for a table needing 240 -- the shape fought the layout. Side by side it
# is 48 by 24, which is also the better read: you compare the poses at a glance.
FRAME_WIDE = PIXELS_WIDE * POSES     # two poses
FRAME_HIGH = POSE_ROWS * 8


class IconPreview(QWidget):

    """Shows one character's combat icon and lets its colours be changed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon: Icon | None = None
        self._charset: bytes = b""
        self._pixels: list[list[int]] = []
        self._parts = None
        self._size = "small"
        self.setMinimumSize(int(FRAME_WIDE * ZOOM), int(FRAME_HIGH * ZOOM))
        self.setMaximumWidth(int(FRAME_WIDE * ZOOM * 2))
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
        """`(scale, x0, y0)` -- an integer zoom, centred, aspect preserved."""
        if not self._pixels:
            return 1, 0, 0
        scale = max(1, min(self.width() // FRAME_WIDE, self.height() // FRAME_HIGH))
        x0 = (self.width() - FRAME_WIDE * scale) // 2
        y0 = (self.height() - FRAME_HIGH * scale) // 2
        return scale, x0, y0

    def _cell_at(self, px: float, py: float) -> int | None:
        if not self._pixels:
            return None
        scale, x0, y0 = self._geometry()
        x = int((px - x0) // scale) // 8
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
                p.fillRect(QRect(x0 + (pose * PIXELS_WIDE + x) * scale,
                                 y0 + into * scale,
                                 scale, scale), colour(index))

        # A hairline between the two poses, so it reads as two frames rather
        # than one tall figure.
        p.setPen(QPen(QColor(255, 255, 255, 70), 1, Qt.PenStyle.DashLine))
        mid = x0 + PIXELS_WIDE * scale
        p.drawLine(mid, y0, mid, y0 + FRAME_HIGH * scale)


class IconEditor(QWidget):
    """Shows one character's combat icon and lets its colours be changed."""

    iconChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parts = None
        self._size = "small"
        self._icon = None
        self._charset = b""
        
        self.preview = IconPreview(self)
        
        self.btn_change = QPushButton("Change the icon…")
        self.btn_change.clicked.connect(self._pick_parts)
        
        self.group_box = QGroupBox("Set Icon Color")
        self.part_combo = QComboBox()
        self.part_combo.addItems([p.title() for p in PART_CLASSES])
        self.color_combo = QComboBox()
        for i, name in enumerate(NAMES):
            self.color_combo.addItem(_swatch(COLOURS[i]), f"{i:2d}  {name}", i)
            
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.btn_change)
        
        form = QFormLayout(self.group_box)
        form.addRow("Part:", self.part_combo)
        form.addRow("Color:", self.color_combo)
        layout.addWidget(self.group_box)
        
        self.part_combo.currentIndexChanged.connect(self._update_color_combo)
        self.color_combo.currentIndexChanged.connect(self._color_selected)

    def set_icon(self, icon: Icon | None, charset: bytes = b"") -> None:
        self._icon = icon
        if charset:
            self._charset = charset
        self.preview.set_icon(icon, charset)
        self._update_color_combo()

    @property
    def icon(self) -> Icon | None:
        return self._icon

    def set_parts(self, parts, size: str = "small") -> None:
        self._parts = parts
        self._size = size

    def _update_color_combo(self):
        if self._icon is None or self._parts is None:
            return
        part_idx = self.part_combo.currentIndex()
        if part_idx < 0:
            return
            
        pc = self._parts.part_colours(bytes(self._icon.colours), bytes(self._icon.shape))
        current_color = pc.get(part_idx, 0)
        
        self.color_combo.blockSignals(True)
        idx = self.color_combo.findData(current_color)
        if idx >= 0:
            self.color_combo.setCurrentIndex(idx)
        self.color_combo.blockSignals(False)

    def _color_selected(self):
        if self._icon is None or self._parts is None:
            return
        part_idx = self.part_combo.currentIndex()
        color_val = self.color_combo.currentData()
        if part_idx < 0 or color_val is None:
            return
            
        pc = self._parts.part_colours(bytes(self._icon.colours), bytes(self._icon.shape))
        pc[part_idx] = color_val
        
        new_colours = self._parts.colours_for(bytes(self._icon.shape), pc, bytes(self._icon.colours))
        self.set_shape(bytes(self._icon.shape), new_colours)

    def _pick_parts(self) -> None:
        if not self._charset or self._parts is None or self._icon is None:
            return
        dialog = PartsPicker(self._parts, self._charset,
                             bytes(self._icon.shape),
                             bytes(self._icon.colours), self._size, self)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        self.set_shape(dialog.shape, dialog.colours)

    def set_shape(self, shape: bytes, colours: bytes) -> None:
        if self._icon is None:
            return
        self._icon = Icon(bytes(shape) + bytes(colours))
        self.preview.set_icon(self._icon, self._charset)
        self._update_color_combo()
        self.iconChanged.emit()

    def set_cell_glyph(self, cell: int, code: int) -> None:
        if self._icon is None or not 0 <= cell < CELLS:
            return
        raw = bytearray(self._icon.raw)
        if raw[cell] == code:
            return
        raw[cell] = code & 0xFF
        self.set_shape(bytes(raw[:CELLS]), bytes(raw[CELLS:]))

    def set_cell_colour(self, cell: int, value: int) -> None:
        if self._icon is None or not 0 <= cell < CELLS:
            return
        raw = bytearray(self._icon.raw)
        if raw[CELLS + cell] == value:
            return
        raw[CELLS + cell] = value & 0x0F
        self.set_shape(bytes(raw[:CELLS]), bytes(raw[CELLS:]))


def _swatch(colour_: QColor):
    from PyQt6.QtGui import QIcon, QPixmap
    pix = QPixmap(16, 16)
    pix.fill(colour_)
    return QIcon(pix)
