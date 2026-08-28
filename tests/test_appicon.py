from __future__ import annotations

"""The application icon: the drawing, the `.ico`, and how it reaches Windows.

Two different things are checked here and they fail for different reasons.

**The drawing.** `ui/appicon.py` puts Font Awesome's `hat-wizard` on a tile,
recoloured and inset and otherwise exactly as Fonticons drew it. What is
measured here is the composition -- the tile is the ground on every side, the
hat clears the edge at 16, it reads in monochrome -- and that the path data is
still theirs: the brim is a separate bar that never touches the cone, at every
size, because moving it would be redrawing somebody else's art.

**The files.** `assets/` is committed, which means it can go stale. Every
artefact is re-rendered here and compared with what is on disk, so a change to
the path data that nobody regenerated fails the build instead of shipping an
executable whose icon is the old drawing. The comparison is the *pixels*,
within a measured tolerance -- see `test_the_committed_assets_are_todays_drawing`
and `test_the_comparison_still_catches_a_change_to_the_drawing`.
"""


import pathlib

import pytest

pytest.importorskip("PyQt6.QtGui")

from PyQt6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402

from tools import genicons  # noqa: E402
from ui import appicon  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICO = ASSETS / "wish.ico"


@pytest.fixture
def app():
    return QGuiApplication.instance() or QGuiApplication([])


# --- the drawing --------------------------------------------------------


def _pixels(size: int) -> list[list[tuple[int, int, int, int]]]:
    image = appicon.image(size).convertToFormat(QImage.Format.Format_RGBA8888)
    raw = image.constBits().asstring(image.sizeInBytes())
    return [[tuple(raw[(y * size + x) * 4:(y * size + x) * 4 + 4])
             for x in range(size)] for y in range(size)]


def _glyph_mask(size: int) -> set[tuple[int, int]]:
    """The pixels that are more hat than tile.

    A midpoint on the red channel: the tile is `#2b3a67` and the hat `#f7f9fb`,
    so the antialiased edge crosses this once and the test is not counting
    fringe pixels as either.
    """
    grid = _pixels(size)
    edge = (0x2b + 0xf7) // 2
    return {(x, y) for y in range(size) for x in range(size)
            if grid[y][x][3] > 128 and grid[y][x][0] > edge}


def _pieces(mask: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    """The mask's four-connected pieces, largest first."""
    seen: set[tuple[int, int]] = set()
    out = []
    for start in mask:
        if start in seen:
            continue
        seen.add(start)
        queue, piece = [start], set()
        while queue:
            x, y = queue.pop()
            piece.add((x, y))
            for step in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                near = (x + step[0], y + step[1])
                if near in mask and near not in seen:
                    seen.add(near)
                    queue.append(near)
        out.append(piece)
    return sorted(out, key=len, reverse=True)


def test_the_hat_is_the_font_awesome_path_and_nothing_else(app):
    """The glyph is drawn, not redrawn. `appicon.glyph` has to hand back the
    same object `iconpaint` builds from the path data -- no cut, no translate,
    no boolean."""
    from ui.iconpaint import painter_path

    assert appicon.glyph() == painter_path(appicon.NAME)
    assert _glyph_mask(16), "nothing was drawn"


def test_the_brim_stays_where_font_awesome_put_it_at_every_size(app):
    """Their drawing, not ours.

    The bar never touches the cone -- the cone closes at y=464 and the bar
    starts at y=512 -- so every size rasterises as two pieces with at least
    one clear row of tile between them. Sliding the bar up at the sizes where
    the gap is tight is the thing this asserts nobody has done again.
    """
    for size in (16, 20, 22, 24, 32, 48, 128, 256):
        pieces = _pieces(_glyph_mask(size))
        assert len(pieces) == 2, f"{size}: {[len(p) for p in pieces]}"
        cone, bar = pieces
        assert max(y for _, y in cone) + 1 < min(y for _, y in bar), size


def test_the_brim_is_the_widest_row_and_the_apex_the_narrowest(app):
    """A hat, not a triangle: the silhouette has to flare at the bottom.

    Measured because the brim is the feature most at risk -- 64 units thick in
    the 640 box, which is 1.6 px at 16 -- and losing it leaves the fin.
    """
    mask = _glyph_mask(16)
    rows = {y: sum(1 for x, yy in mask if yy == y) for _, y in mask}
    bottom = max(rows)
    assert rows[bottom] == max(rows.values()), rows
    assert rows[bottom] >= 8, f"the brim is {rows[bottom]} px wide at 16"
    assert rows[min(rows)] <= 3, "the apex is not a point"


def test_the_tile_reads_in_monochrome(app):
    """Windows draws the icon greyscale in places and describes it in none."""
    def grey(colour):
        r, g, b, _ = colour
        return 0.299 * r + 0.587 * g + 0.114 * b

    assert grey(appicon.GLYPH.getRgb()) - grey(appicon.TILE.getRgb()) > 120


def test_the_tile_fills_the_square_apart_from_its_corners(app):
    """A shape on transparency is grey pixels on an unknown taskbar -- §2 of
    `docs/132-logo.md`. The tile is the ground, so it has to be opaque
    everywhere but the rounded corners."""
    grid = _pixels(32)
    assert grid[16][0][3] == 255 and grid[16][31][3] == 255      # left, right
    assert grid[0][16][3] == 255 and grid[31][16][3] == 255      # top, bottom
    assert grid[0][0][3] == 0, "the corner is not rounded"


def test_the_hat_never_touches_the_edge(app):
    """One pixel of tile all the way round, at the size where there is only
    one pixel to spare."""
    mask = _glyph_mask(16)
    assert not any(x in (0, 15) or y in (0, 15) for x, y in mask)


# --- the icon Qt hands the window ---------------------------------------


def test_the_window_icon_carries_a_drawing_per_size(app):
    """Qt scales an icon it has no entry for; 16 and 32 are the two that
    matter and both are drawn rather than derived."""
    icon = appicon.app_icon()
    have = {(s.width(), s.height()) for s in icon.availableSizes()}
    assert {(16, 16), (32, 32)} <= have
    assert have == {(s, s) for s in appicon.WINDOW_SIZES}


def test_the_application_is_dressed_before_the_first_window(app, monkeypatch):
    """`dress` is what puts the icon on the taskbar button of a running
    window, and the desktop file name is what makes GNOME and KDE find the
    hicolor PNGs."""
    from automap import paths
    from wish.window import dress

    dress(app)
    assert not app.windowIcon().isNull()
    assert app.desktopFileName() == paths.APP
    assert app.applicationName() == "Wish"


def test_the_about_box_shows_the_icon(app):
    """Help > About is the one place the picture is the point."""
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    if QApplication.instance() is None:
        pytest.skip("no QApplication")
    from wish.about import PICTURE, box

    dialog = box()
    try:
        assert not dialog.iconPixmap().isNull()
        assert dialog.iconPixmap().deviceIndependentSize().width() == PICTURE
    finally:
        dialog.deleteLater()


# --- the files under assets/ --------------------------------------------


def _entries() -> list[dict]:
    """`wish.ico`'s directory, as the generator's own parser reads it."""
    return genicons.ico_entries(ICO.read_bytes())


def test_the_ico_holds_the_sizes_windows_asks_for():
    """20, 24 and 40 are not padding: they are what Windows requests at 125 %,
    150 % and 250 % scaling instead of rounding to 16 or 32."""
    assert [e["size"] for e in _entries()] == sorted(genicons.ICO_SIZES)
    assert {16, 32} <= set(genicons.ICO_SIZES)


def test_every_ico_entry_is_32_bit():
    for entry in _entries():
        assert (entry["bpp"], entry["planes"]) == (32, 1), entry["size"]
        assert entry["size"] == entry["height"]


def test_the_small_entries_are_dibs_and_the_256_is_a_png():
    """The mix the shell documents. A DIB at 256 is a quarter of a megabyte,
    and a PNG below 256 is a form the older shell code paths did not read."""
    for entry in _entries():
        png = entry["payload"][:8] == b"\x89PNG\r\n\x1a\n"
        assert png == (entry["size"] >= genicons.PNG_FROM), entry["size"]


def test_the_16_is_drawn_and_not_a_squeezed_256(app):
    """The whole reason the file has eight entries. A 256 scaled to 16 is
    mush; this compares the stored pixels with a fresh render at 16.

    To `genicons.TOLERANCE`, for the reason the comparison of the whole of
    `assets/` is: the committed bytes were rasterised on somebody else's
    machine. A downscale would be out by a hundred, not by two.
    """
    entry = next(e for e in _entries() if e["size"] == 16)
    header = 40
    stride = 16 * 4
    stored = entry["payload"][header:header + stride * 16]
    # A DIB is bottom-up, and BGRA where the renderer works in RGBA.
    rows = [stored[y * stride:(y + 1) * stride] for y in reversed(range(16))]
    fresh = _pixels(16)
    for y, row in enumerate(rows):
        for x in range(16):
            b, g, r, a = row[x * 4:x * 4 + 4]
            off = max(abs(u - v) for u, v in zip((r, g, b, a), fresh[y][x]))
            assert off <= genicons.TOLERANCE, (x, y, off)


def test_the_committed_assets_are_todays_drawing(app):
    """`assets/` is committed, so it can go stale. Regenerate it with
    `python3 tools/genicons.py` when this fails.

    **Pixels, not bytes.** This compared the files byte for byte until CI
    turned red on every runner. A PNG's bytes are libpng's and zlib's, and
    `ldd libQt6Gui.so.6` on Linux resolves `libpng16.so.16` and `libz.so.1` to
    the *host's* copies while the Windows wheel carries its own. Qt hands the
    encoder pixels and the encoder writes whatever file it likes.

    **And pixels within a tolerance.** That went red too, on all four runners
    at once: 8 of 65536 pixels at 256, 8 of 484 at 22, 1 of 4096 at 64, each
    by 1 of 255. Qt's rasteriser does not round the last bit of an antialiased
    edge the same way on every host. `genicons.TOLERANCE` and `genicons.MOST`
    are the room that leaves, and
    `test_the_comparison_still_catches_a_change_to_the_drawing` is the proof
    that it is not so much room that a real change gets through.
    """
    stale = {str(path.relative_to(ROOT)): why
             for path, why in genicons.differences(ASSETS).items()}
    assert not stale, f"run tools/genicons.py: {stale}"


@pytest.mark.parametrize("attribute,value", [("INSET", 0.1001),
                                             ("RADIUS", 0.1801),
                                             ("TILE", QColor("#2b3a68"))])
def test_the_comparison_still_catches_a_change_to_the_drawing(
        app, monkeypatch, attribute, value):
    """The tolerance above has to be noise-wide, not change-wide.

    Each of these is the smallest perturbation of its kind worth arguing
    about -- the inset and the corner radius moved by one part in a thousand,
    and a colour by a single unit of 255 -- and each has to leave the
    committed `assets/` looking stale. Measured when the bounds were chosen:
    a part in a thousand off the inset goes 4 of 255 out at 24 and 12 at 256,
    and a one-unit colour change moves 70 % of the pixels at every size.
    """
    monkeypatch.setattr(appicon, attribute, value)
    assert genicons.differences(ASSETS), f"{attribute}={value} slipped through"


def test_the_hicolor_tree_covers_gnome_and_kde():
    """22 is GNOME's panel size and 24 is KDE's. Neither is an export default
    and a missing one is a blurred panel icon."""
    assert {22, 24} <= set(genicons.HICOLOR_SIZES)
    for size in genicons.HICOLOR_SIZES:
        path = (ASSETS / "icons" / "hicolor" / f"{size}x{size}" / "apps"
                / "wish.png")
        assert path.exists(), path
        image = QImage(str(path))
        assert (image.width(), image.height()) == (size, size)


def test_the_windows_executable_carries_the_ico():
    """Windows takes a pinned shortcut's icon and Explorer's from the exe's
    own resource, not from Qt. `wish.spec` is where that is set."""
    spec = (ROOT / "wish.spec").read_text(encoding="utf-8")
    assert 'ICON = "assets/wish.ico"' in spec
    assert "icon=ICON," in spec
    assert ICO.exists()
