from __future__ import annotations

"""The icon the window gets is the artist's committed PNG, scaled down."""

import pathlib

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

LOGO = pathlib.Path(__file__).resolve().parent.parent / "assets" / "logo"
ARGB = QImage.Format.Format_ARGB32_Premultiplied


def _committed_pngs() -> dict[int, QImage]:
    """Every `mark-N.png` under `assets/logo`, by side, found by name so
    nothing here reads the module that ships them."""
    return {int(path.stem.split("-")[1]): QImage(str(path)).convertToFormat(ARGB)
            for path in LOGO.glob("mark-[0-9]*.png")}


def test_the_window_icon_is_the_committed_png_scaled_down():
    """At every size the window's icon holds, the pixels are the smallest
    committed PNG no smaller than that size, scaled down whole and nothing
    else -- the file the artist sent, not a redrawing of it."""
    from wish.window import dress

    app = QApplication.instance() or QApplication([])
    dress(app)
    icon = app.windowIcon()
    sizes = sorted(size.width() for size in icon.availableSizes())
    committed = _committed_pngs()
    assert sizes and sorted(committed) == [80, 150, 200, 500]
    for size in sizes:
        side = min(s for s in committed if s >= size)
        want = committed[side].scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        got = icon.pixmap(size, size).toImage().convertToFormat(ARGB)
        assert got == want, f"the window's {size}px icon is not mark-{side}.png scaled"
