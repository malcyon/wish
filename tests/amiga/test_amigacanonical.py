"""`screens.canonical`: any exact emulator frame becomes the 720x568 crop the guard rules were cut from."""

from __future__ import annotations

import json
import pathlib

import pytest
from PIL import Image

from tools.amiga import screens
from tools.amiga.winuaesession import RouteError

HERE = pathlib.Path(screens.__file__).parent
TITLES = ("pool", "curse", "silver_blades", "darkness")


def _native(width=360, height=284):
    """An Amiga-pixel image in the 12-bit palette with a different colour in every row and column."""
    image = Image.new("RGB", (width, height))
    image.putdata([(17 * (x % 16), 17 * (y % 16), 17 * ((x + y) % 16))
                   for y in range(height) for x in range(width)])
    return image


def _replicated(native, k, origin, size):
    """`native` placed at `origin` (Amiga pixels) in a `size` frame of `k`x copies, the rest red."""
    frame = Image.new("RGB", (size[0] // k, size[1] // k), (255, 0, 0))
    frame.paste(native, origin)
    return frame.resize(size, Image.NEAREST)


def test_a_frame_that_is_already_the_winuae_crop_comes_back_unchanged():
    crop = _native().resize(screens.CANONICAL, Image.NEAREST)
    assert screens.canonical(crop).tobytes() == crop.tobytes()
    assert screens.canonical(crop.convert("RGBA")).mode == "RGB"


def test_fsuaes_own_screenshot_is_cut_to_the_window_and_doubled():
    native = _native()
    frame = _replicated(native, 2, (8, 2), (754, 576))
    got = screens.canonical(frame)
    assert got.size == screens.CANONICAL
    assert got.tobytes() == native.resize(screens.CANONICAL, Image.NEAREST).tobytes()
    # The corners of the window are the corners of the crop; the red border is gone.
    assert got.getpixel((0, 0)) == native.getpixel((0, 0)) and got.getpixel((719, 567)) == native.getpixel((359, 283))
    assert (255, 0, 0) not in {got.getpixel((x, y)) for x in (0, 719) for y in (0, 567)}


def test_a_threefold_frame_with_its_own_origin_gives_the_same_crop():
    native = _native()
    frame = _replicated(native, 3, (5, 7), (3 * 370, 3 * 295))
    got = screens.canonical(frame, replication=3, origin=(5, 7))
    assert got.tobytes() == native.resize(screens.CANONICAL, Image.NEAREST).tobytes()


def test_a_known_size_takes_a_replication_and_origin_given_beside_it():
    native = _native()
    frame = _replicated(native, 2, (6, 1), (754, 576))
    assert screens.canonical(frame, origin=(6, 1)).tobytes() == native.resize(
        screens.CANONICAL, Image.NEAREST).tobytes()


def test_a_frame_of_no_known_size_and_no_calibration_is_blocked():
    with pytest.raises(RouteError, match="no known way to cut a 800x600 frame"):
        screens.canonical(Image.new("RGB", (800, 600)))


def test_a_filtered_frame_is_not_passed_off_as_an_exact_capture():
    frame = _replicated(_native(), 2, (8, 2), (754, 576))
    frame.putpixel((100, 100), (1, 2, 3))     # one pixel breaks a 2x2 block
    with pytest.raises(RouteError, match="not an exact capture"):
        screens.canonical(frame)


def test_a_window_that_does_not_fit_the_frame_is_blocked():
    with pytest.raises(RouteError, match="does not fit"):
        screens.canonical(Image.new("RGB", (754, 576)), origin=(100, 100))


def test_canonical_file_writes_the_crop_as_a_png(tmp_path):
    native = _native()
    _replicated(native, 2, (8, 2), (754, 576)).save(tmp_path / "shot.png")
    screens.canonical_file(tmp_path / "shot.png", tmp_path / "crop.png")
    with Image.open(tmp_path / "crop.png") as image:
        assert image.tobytes() == native.resize(screens.CANONICAL, Image.NEAREST).tobytes()


def _examples(root):
    """Every guard rule that names an example crop, as `(title, state, rule)`."""
    rules = []
    for title in TITLES:
        spec = json.loads((HERE / f"guards_{title}.json").read_text())
        for kind in ("guards", "identity"):
            for state, value in spec.get(kind, {}).items():
                for rule in value if isinstance(value, list) else [value]:
                    if rule.get("example"):
                        rules.append((title, f"{kind}/{state}", rule))
    return rules


def test_canonical_is_the_identity_on_every_kept_winuae_crop_and_every_rule_still_matches_its_example():
    """Reads the crops kept from live runs, so it skips on a machine without them."""
    from tools.registry import scratch

    root = scratch.cache_dir("acceptance")
    present = [(t, s, r) for t, s, r in _examples(root) if (root / r["example"]).is_file()]
    if not present:
        pytest.skip("the kept WinUAE example crops are not on this machine")
    for title, state, rule in present:
        path = root / rule["example"]
        with Image.open(path) as image:
            assert screens.canonical(image).tobytes() == image.convert("RGB").tobytes(), (title, state)
        box = tuple(rule["box"])
        assert screens.box_digests(path, [box])[box] == rule["sha256"], (title, state, rule["example"])
