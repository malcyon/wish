from __future__ import annotations

"""The application icon: the drawing, the `.ico`, and how it reaches Windows.

Two different things are checked here and they fail for different reasons.

**The drawing.** `ui/appicon.py` renders the artist's own `assets/logo/mark.svg`
at whatever size is asked for. What is measured here is that the asset is
still theirs -- a hash pinned against the committed file, because moving a
point would be redrawing somebody else's art -- and that the square it
delivers is what an application icon needs: opaque on every side, so there is
nothing for an unknown taskbar or dock to show through.

**The files.** `assets/` is committed, which means it can go stale. Every
artefact is re-rendered here and compared with what is on disk, so a change to
the asset that nobody regenerated fails the build instead of shipping an
executable whose icon is the old drawing. The comparison is the *pixels*,
within a measured tolerance -- see `test_the_committed_assets_are_todays_drawing`
and `test_the_comparison_still_catches_a_change_to_the_drawing`.
"""


import hashlib
import pathlib

import pytest

pytest.importorskip("PyQt6.QtGui")

from PyQt6.QtGui import QGuiApplication, QImage  # noqa: E402

from tools import genicons  # noqa: E402
from ui import appicon  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICO = ASSETS / "wish.ico"

#: `assets/logo/mark.svg`, as delivered on 2026-09-05. Pinned so an edit to
#: the artist's file -- even a well-meant one, tuning a curve for 16px -- fails
#: here instead of shipping unnoticed. `.claude/rules/art.md`: the answer to a
#: size that does not work is a different icon, never a nudged one.
MARK_SHA256 = "8457f44bd64bdd6e7894695eb48f5e5ea82db9067132890829a0ad14e9923027"


@pytest.fixture
def app():
    return QGuiApplication.instance() or QGuiApplication([])


# --- the drawing --------------------------------------------------------


def _pixels(size: int) -> list[list[tuple[int, int, int, int]]]:
    image = appicon.image(size).convertToFormat(QImage.Format.Format_RGBA8888)
    raw = image.constBits().asstring(image.sizeInBytes())
    return [[tuple(raw[(y * size + x) * 4:(y * size + x) * 4 + 4])
             for x in range(size)] for y in range(size)]


def test_the_asset_is_the_artists_own_file_unmodified():
    """The whole of `art.md`'s ban on moving a point, as a checkable fact."""
    assert appicon.ASSET.exists(), appicon.ASSET
    digest = hashlib.sha256(appicon.ASSET.read_bytes()).hexdigest()
    assert digest == MARK_SHA256, (
        "assets/logo/mark.svg has changed -- if this is a deliberate new "
        "delivery from the artist, update MARK_SHA256 to match; if it is an "
        "edit of the existing file, it should not be one")


def test_the_asset_is_a_valid_svg(app):
    from PyQt6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(appicon.ASSET))
    assert renderer.isValid()


def test_the_icon_is_opaque_at_every_size(app):
    """The mark carries its own ground -- `docs/132-logo.md` §2 -- so unlike
    the stand-ins before it there is no tile to composite and nothing here
    should ever be transparent, corners included."""
    for size in (16, 32, 256):
        grid = _pixels(size)
        corners = [grid[0][0], grid[0][size - 1],
                  grid[size - 1][0], grid[size - 1][size - 1]]
        assert all(a == 255 for *_, a in corners), (size, corners)
        assert all(a == 255 for row in grid for *_, a in row), size


def test_the_icon_is_not_blank_at_16(app):
    """The smallest anyone ever sees it. Some part of the gold mark has to
    read against the dark ground, or there would be nothing here to see."""
    grid = _pixels(16)
    ground = grid[0][0]
    lit = sum(1 for row in grid for px in row
             if sum(abs(a - b) for a, b in zip(px, ground)) > 60)
    assert lit >= 8, f"only {lit} pixels differ from the ground at 16px"


def test_the_icon_reads_the_same_drawing_at_every_size(app):
    """Every size is rendered from the vector, never a downscale of another
    size -- so the ground colour, sampled well away from any stroke, is the
    same at 16 as at 256."""
    corner_16 = _pixels(16)[0][0]
    corner_256 = _pixels(256)[0][0]
    assert corner_16 == corner_256


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


def test_the_comparison_still_catches_a_change_to_the_drawing(app, monkeypatch):
    """The tolerance above has to be noise-wide, not change-wide.

    Renders a slightly different square -- the mark shifted by a single
    device pixel at every size -- and checks the comparison still calls it
    stale. A shift is used rather than a colour change because there is no
    tunable constant left in `ui/appicon.py` to perturb: the drawing is now a
    fixed asset, not a set of fractions.
    """
    original = appicon.image

    def shifted(size):
        image = original(size)
        nudged = QImage(image.size(), image.format())
        nudged.fill(0)
        from PyQt6.QtGui import QPainter
        p = QPainter(nudged)
        p.drawImage(1, 0, image)
        p.end()
        return nudged

    monkeypatch.setattr(appicon, "image", shifted)
    assert genicons.differences(ASSETS), "a shifted render slipped through"


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
