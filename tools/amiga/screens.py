"""Pixel-box guards: exact static screen regions that recognise a known Amiga screen."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any

from tools.amiga.winuaesession import RouteError


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
    """Refuse a uniform box or one that also recognises a neighbouring screen."""
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
