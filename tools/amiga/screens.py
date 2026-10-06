"""Pixel-box guards: exact static screen regions that recognise a known Amiga screen."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any

from tools.amiga.winuaesession import RouteError

#: The size of WinUAE's client area, which every guard rule's box is cut from.
CANONICAL = (720, 568)
#: The WinUAE window in Amiga pixels: 360 columns by 284 rows, doubled to `CANONICAL`.
_WINDOW = (360, 284)
#: The screenshots an emulator writes itself: size -> (copies of each Amiga pixel
#: across and down, the window's left and top in Amiga pixels). FS-UAE's own
#: screenshot is a 377x288 frame doubled, and the window sits at column 8, row 2.
#: WinUAE's own screenshot (`DBG sc`) is already doubled, a 752x574 frame with the
#: window at the same column and row, so its crop is the plain cut at (16, 4).
FRAMES = {(754, 576): (2, (8, 2)), (752, 574): (2, (8, 2))}


class NotExactCapture(RouteError):
    """A frame that is not whole copies of each Amiga pixel, such as a hires AmigaDOS window."""


def _is_blank(rgb) -> bool:
    """Whether the frame is one flat colour, or two in whole rows: a window still being drawn."""
    from PIL import Image  # noqa: PLC0415

    colours = rgb.getcolors(2)
    if colours is None:
        return False
    if len(colours) == 1:
        return True
    column = rgb.resize((1, rgb.height), Image.NEAREST)
    return column.resize(rgb.size, Image.NEAREST).tobytes() == rgb.tobytes()


def canonical(image, *, replication: int | None = None, origin: tuple[int, int] | None = None):
    """The frame as WinUAE's crop shows it: 720x568, each Amiga pixel doubled.

    A frame already that size is returned as it is, so the rules apply to a
    WinUAE crop unchanged. Any other size must be a known emulator screenshot
    (`FRAMES`) or be given its `replication` and `origin`; each copy-block of
    the window must hold one colour, because a filtered or resampled frame
    would match no rule and must not be passed off as an exact one.
    """
    from PIL import Image  # noqa: PLC0415

    rgb = image.convert("RGB")
    if rgb.size == CANONICAL and replication is None:
        return rgb
    known = FRAMES.get(rgb.size)
    if replication is None or origin is None:
        if known is None:
            if _is_blank(rgb):
                raise NotExactCapture(f"the {rgb.width}x{rgb.height} frame holds no Amiga picture yet")
            raise RouteError(f"no known way to cut a {rgb.width}x{rgb.height} frame to the Amiga screen")
        replication = known[0] if replication is None else replication
        origin = known[1] if origin is None else origin
    left, top = origin[0] * replication, origin[1] * replication
    box = (left, top, left + _WINDOW[0] * replication, top + _WINDOW[1] * replication)
    if replication < 1 or box[0] < 0 or box[1] < 0 or box[2] > rgb.width or box[3] > rgb.height:
        raise RouteError(f"the Amiga screen does not fit a {rgb.width}x{rgb.height} frame at {origin}")
    window = rgb.crop(box)
    native = window.resize(_WINDOW, Image.NEAREST)
    if native.resize(window.size, Image.NEAREST).tobytes() != window.tobytes():
        raise NotExactCapture(f"the frame is not {replication}x copies of each Amiga pixel, "
                              "so it is not an exact capture")
    return native.resize(CANONICAL, Image.NEAREST)


def canonical_file(source: pathlib.Path, target: pathlib.Path) -> None:
    """Write `source`'s canonical frame to `target` as a PNG."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(source) as image:
        canonical(image).save(target)


def _box_pixels(image_path: pathlib.Path, box, state: str) -> bytes:
    """The RGB pixels inside `box` of a cropped Amiga screen."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(image_path) as image:
        _check_box(box, image, state)
        return image.convert("RGB").crop(tuple(box)).tobytes()


def _check_box(box, image, state: str) -> None:
    if (len(box) != 4 or min(box) < 0 or box[2] > image.width
            or box[3] > image.height or box[0] >= box[2]
            or box[1] >= box[3]):
        raise RouteError(f"invalid crop box for {state}")


def box_digests(image_path: pathlib.Path, boxes, state: str = "guard") -> dict[tuple, str]:
    """Hash each requested box while opening the crop once."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        result = {}
        for box in boxes:
            _check_box(box, rgb, state)
            result[tuple(box)] = hashlib.sha256(rgb.crop(tuple(box)).tobytes()).hexdigest()
        return result


def _box_digest(image_path: pathlib.Path, box, state: str) -> str:
    """SHA-256 of the RGB pixels inside `box` of a cropped Amiga screen."""
    return hashlib.sha256(_box_pixels(image_path, box, state)).hexdigest()


def _box_is_uniform(image_path: pathlib.Path, box, state: str) -> bool:
    """Whether every pixel in `box` is one colour, so the box matches any screen showing it."""
    pixels = _box_pixels(image_path, box, state)
    return len({pixels[i:i + 3] for i in range(0, len(pixels), 3)}) == 1


def guard_rule(image_path: pathlib.Path, box, state: str = "guard") -> dict[str, Any]:
    """The `PixelGuards` rule that recognises `box` exactly as this crop shows it."""
    box = [int(n) for n in box]
    return {"box": box, "sha256": _box_digest(pathlib.Path(image_path), box, state)}


def checked_rule(crop: pathlib.Path, box, state: str, unlike) -> dict[str, Any]:
    """Block a uniform box or one that also recognises a neighbouring screen."""
    rule = guard_rule(crop, box, state)
    for other in unlike:
        if _box_digest(other, box, state) == rule["sha256"]:
            raise RouteError(f"{state} box {box} also matches {other}")
    if _box_is_uniform(crop, box, state):
        raise RouteError(f"{state} box {box} is one colour and would match "
                         f"any screen showing it")
    return rule


def rules_of(value: Any) -> list:
    """A state's alternative rules: a single rule stays one dict, several are a list."""
    return list(value) if isinstance(value, list) else [value]


class PixelGuards:
    """Exact static regions from measured captures; an unknown screen fails closed.

    A state holds one rule, or a list of alternatives when the same screen looks
    different by party (a sheet with an item row and one without), and matches
    when any of them does.
    """

    def __init__(self, path: pathlib.Path):
        self.rules = json.loads(pathlib.Path(path).read_text())
        for state, value in self.rules.items():
            alternatives = rules_of(value)
            if not alternatives or any(
                    not isinstance(rule, dict) or not isinstance(rule.get("box"), list)
                    or not re.fullmatch(r"[0-9a-f]{64}", str(rule.get("sha256")))
                    for rule in alternatives):
                raise RouteError(f"screen guard for {state} needs a box and a sha256")

    def __contains__(self, state: str) -> bool:
        return state in self.rules

    def __call__(self, state: str, image_path: pathlib.Path) -> bool:
        value = self.rules.get(state)
        if value is None:
            return False
        return any(_box_digest(image_path, rule["box"], state) == rule["sha256"]
                   for rule in rules_of(value))


def _guards(guard: Any, state: str) -> bool:
    """Whether `guard` has a rule for `state`; a bare callable guards every state."""
    if guard is None:
        return False
    try:
        return state in guard
    except TypeError:
        return True


def _has_rule(guard: Any, state: str) -> bool:
    """Whether a guard *map* holds `state`; a bare callable holds none, so no interstitial fires."""
    return hasattr(guard, "__contains__") and state in guard
