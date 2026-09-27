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
        if (len(box) != 4 or min(box) < 0 or box[2] > image.width
                or box[3] > image.height or box[0] >= box[2]
                or box[1] >= box[3]):
            raise RouteError(f"invalid crop box for {state}")
        return image.convert("RGB").crop(tuple(box)).tobytes()


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


class PixelGuards:
    """Exact static regions from measured captures; an unknown screen fails closed."""

    def __init__(self, path: pathlib.Path):
        self.rules = json.loads(pathlib.Path(path).read_text())
        for state, rule in self.rules.items():
            if (not isinstance(rule, dict) or not isinstance(rule.get("box"), list)
                    or not re.fullmatch(r"[0-9a-f]{64}", str(rule.get("sha256")))):
                raise RouteError(f"screen guard for {state} needs a box and a sha256")

    def __contains__(self, state: str) -> bool:
        return state in self.rules

    def __call__(self, state: str, image_path: pathlib.Path) -> bool:
        rule = self.rules.get(state)
        if rule is None:
            return False
        return _box_digest(image_path, rule["box"], state) == rule["sha256"]


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
