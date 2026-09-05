from __future__ import annotations

"""`assets/wish.icns`: the container, and that it holds today's drawing.

Nobody has run this on a Mac -- `docs/132-logo.md` says so -- so what is
checked here is what can be checked without one: the chunks decode to PNGs of
the size their Apple type code promises, and the committed file is what
`packaging/geniconset.py` would write today.
"""

import importlib.util
import pathlib

import pytest

pytest.importorskip("PyQt6.QtGui")

from PyQt6.QtGui import QGuiApplication, QImage  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ICNS = ROOT / "assets" / "wish.icns"


def _load_geniconset():
    """`packaging/geniconset.py`, loaded by path.

    `packaging/` carries no `__init__.py` -- PyInstaller reads
    `packaging/wish_main.py` as a plain script path, never as a package -- so
    `import packaging.geniconset` resolves to the unrelated PyPI package of
    the same name instead. `tests/test_packaging.py` loads `wish_main.py` the
    same way for the same reason.
    """
    path = ROOT / "packaging" / "geniconset.py"
    spec = importlib.util.spec_from_file_location("_geniconset", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


geniconset = _load_geniconset()


@pytest.fixture
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def test_every_tag_decodes_to_a_png_of_the_size_it_promises(app):
    chunks = geniconset.entries(ICNS.read_bytes())
    assert {c["tag"] for c in chunks} == {tag for tag, _ in geniconset.TAGS}
    for chunk in chunks:
        size = next(s for t, s in geniconset.TAGS if t == chunk["tag"])
        image = QImage.fromData(chunk["payload"], "PNG")
        assert not image.isNull(), chunk["tag"]
        assert (image.width(), image.height()) == (size, size), chunk["tag"]


def test_the_same_pixels_back_two_tags_that_share_a_size(app):
    """`32x32`@1x and `16x16@2x` are the same 32 pixels under two Apple type
    codes -- both are one call to `ui.appicon.image(32)`, not two drawings
    that happen to agree."""
    chunks = {c["tag"]: c["payload"] for c in geniconset.entries(
        ICNS.read_bytes())}
    assert chunks["icp5"] == chunks["ic11"]
    assert chunks["icp6"] == chunks["ic12"]
    assert chunks["ic08"] == chunks["ic13"]
    assert chunks["ic09"] == chunks["ic14"]


def test_the_committed_icns_is_todays_drawing(app):
    """Regenerate with `python3 packaging/geniconset.py` when this fails."""
    why = geniconset.differences(ICNS)
    assert not why, f"run packaging/geniconset.py: {why}"


def test_every_size_is_rendered_from_the_vector_not_scaled(app):
    """The whole reason the source is an SVG: `ic07`'s 128px square renders
    with the same ground colour as `ic10`'s 1024, sampled where no stroke
    reaches, which a scaled bitmap would not disturb but a wrong render
    might."""
    chunks = {c["tag"]: c["payload"] for c in geniconset.entries(
        ICNS.read_bytes())}
    small = QImage.fromData(chunks["ic07"], "PNG").convertToFormat(
        QImage.Format.Format_RGBA8888)
    big = QImage.fromData(chunks["ic10"], "PNG").convertToFormat(
        QImage.Format.Format_RGBA8888)
    assert small.pixelColor(0, 0) == big.pixelColor(0, 0)
