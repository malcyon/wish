"""The application icon: the drawing, the `.ico`, and how it reaches Windows.

Two different things are checked here and they fail for different reasons.

**The drawing.** `ui/appicon.py` puts Font Awesome's `hat-wizard` on a tile,
and the whole question `docs/109-icon-choices.md` asks of a glyph is whether it
survives at the smallest size somebody sees it. This one does not, unaided: its
brim is a bar that never touches the cone, so below `appicon.CLOSE_BELOW` the
bar is slid up. So the 16 is rendered and *measured* -- one connected
silhouette, a brim wide enough to count, and enough contrast against the tile
to read in monochrome -- rather than merely produced, and 22 is measured too,
because that is where the gap is claimed to start reading as a gap.

**The files.** `assets/` is committed, which means it can go stale. Every
artefact is re-rendered here and compared with what is on disk, so a change to
the path data that nobody regenerated fails the build instead of shipping an
executable whose icon is the old drawing. The comparison is the *pixels*: a
PNG's bytes belong to libpng and zlib, which Qt links from the host on Linux
and bundles on Windows, and two machines encoded the same drawing into
different files -- see `test_the_committed_assets_are_todays_drawing`.
"""

from __future__ import annotations

import pathlib

import pytest

pytest.importorskip("PyQt6.QtGui")

from PyQt6.QtGui import QGuiApplication, QImage  # noqa: E402

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


def test_the_hat_is_one_connected_silhouette_at_16(app):
    """The failure `109` says kills a glyph is separation, not mush.

    `hat-wizard` was rejected for the map at 13 px for exactly this: its brim
    is a separate bar and the icon reads as a shark's fin. The app icon slides
    the bar up below `CLOSE_BELOW`, and this is what proves the result is one
    piece after rasterising rather than merely in the vector.
    """
    mask = _glyph_mask(16)
    assert mask, "nothing was drawn"
    assert len(_pieces(mask)) == 1, "the brim came away from the cone"


def test_the_brim_is_slid_up_below_22_and_left_where_it_was_above(app):
    """`CLOSE_BELOW` is a measurement, so it is measured here.

    Fonticons draw the brim as a bar that never touches the cone, and that is
    the drawing rather than a fault: from 22 px up a whole row of tile pixels
    survives between the two and the icon reads as a hat resting on a table.
    At 20 and 16 nothing survives -- the cone's foot and the bar's top both
    land on part-covered pixels and it is a fin over a grey smear -- so those
    two sizes get the bar slid up instead.
    """
    for size in (16, 20):
        assert size < appicon.CLOSE_BELOW
        assert len(_pieces(_glyph_mask(size))) == 1, size
    for size in (22, 24, 32, 48):
        assert size >= appicon.CLOSE_BELOW
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
    mush; this compares the stored pixels with a fresh render at 16."""
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
            assert (r, g, b, a) == fresh[y][x], (x, y)


def test_the_committed_assets_are_todays_drawing(app):
    """`assets/` is committed, so it can go stale. Regenerate it with
    `python3 tools/genicons.py` when this fails.

    **Pixels, not bytes.** This compared the files byte for byte until CI
    turned red on three of four runners with the same six names: `wish.ico`,
    `wish.png` and the 22, 48, 64 and 256 hicolor PNGs. The other four hicolor
    PNGs -- 16, 24, 32, 128 -- were byte-identical on every one of them, and
    that is the whole diagnosis. A rasterising difference cannot be that
    selective: the smallest edit worth catching moves pixels at *every* size
    (one path point by 1/640 moves 10 px at 16 and 218 at 256), and an
    arithmetic wobble a thousand times smaller than that -- one ulp on the
    scale factor -- moves none anywhere. A compressor's output, on the other
    hand, differs exactly where the data leads it to.

    And the compressor is not ours. `ldd libQt6Gui.so.6` on Linux resolves
    `libpng16.so.16` and `libz.so.1` to the *host's* copies; the Windows wheel
    carries its own. Qt hands the encoder the pixels and the encoder writes
    whatever file it likes -- so the pixels are what is asserted here, and the
    committed bytes only have to decode to them.
    """
    stale = {str(path.relative_to(ROOT)): why
             for path, why in genicons.differences(ASSETS).items()}
    assert not stale, f"run tools/genicons.py: {stale}"


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
