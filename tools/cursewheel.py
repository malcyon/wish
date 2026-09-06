#!/usr/bin/env python3
"""Answer DOS Curse of the Azure Bonds' code wheel from a screenshot.

Curse asks its wheel before the main menu, so **every** driven DOS Curse
session has to answer it, and an agent that cannot is stopped at the title.
The arithmetic behind the answer is worked out in
`~/src/goldbox-codewheel/coab/notes/copy-protection.md` and computed by that
repository's `coab/analysis/wheel.py`; what was missing was the reading --
turning the frame on screen into the four numbers that function wants.

    tools/cursewheel.py --shot work/dosbox/inst/0/shots/008-wheel.png --box 4

prints the two rune indices with their scores, the path it read, and the
character to type.

**The frame.** The prompt draws an Espruar rune above a Dethek one, as two
tiles at (143,31) and (143,63) in the 320x200 frame, embossed in white, red
and yellow with a black shadow over two greens.  Everything in a tile that is
not one of the two greens or the border's two greys is the glyph, and that
mask is enough to tell the 26 Espruar and 22 Dethek runes apart: the reference
bitmaps in `coab/images/` are the same runes rendered from the C64's own
`SECSET10`, so the two are the same shapes in different paint, compared as
normalised grids with a cell of slack rather than pixel for pixel.

Read on the first frame it met -- Espruar 1 at 0.96 against 0.91 for the
runner-up, Dethek 2 at 0.98 against 0.88 -- and the answer it computed, `U`,
was accepted by the game first try.

**The path** is the row under the runes: `----------`, `..........` or
`-..-..-..-`, drawn as marks whose *height in the character cell* is what
separates them -- dashes sit in the middle, dots at the bottom.  That is read
here; the **box number is not**, because it is one 8x8 digit glyph in the
game's own display font and reading it needs a font this tool does not have.
Pass `--box`, which is the number the prompt prints in words a person can
read at a glance.

The wheel table and the two arithmetics come from
`$WISH_CODEWHEEL`, default `~/src/goldbox-codewheel` -- kept out of this
repository deliberately, like the disks.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

#: The two rune tiles' **interiors**, as (left, top, width, height) in the
#: 320x200 frame.  Measured off a live prompt on 2026-09-05 and inset three
#: pixels from the tile's own grey border on purpose: the border's corner
#: pixels otherwise widen the glyph's bounding box, and everything below is
#: scaled by that box, so two stray pixels move every answer.
TILES = {"espruar": (146, 34, 20, 21), "dethek": (146, 66, 20, 21)}

#: What is **not** the glyph inside a tile: two greens for the background and
#: two greys for the border.  The glyph is drawn embossed in white, red and
#: yellow with a black shadow, and taking "anything that is not background"
#: keeps the shadow, which is most of the outline's other side.
BACKGROUND = {(0, 170, 0), (85, 255, 85), (170, 170, 170), (85, 85, 85)}

#: The path's term into the wheel arithmetic, by the index `wheel.py` uses.
PATH_NAMES = ("----------", "..........", "-..-..-..-")

GRID = 16


def wheel_repo() -> pathlib.Path:
    return pathlib.Path(os.environ.get("WISH_CODEWHEEL")
                        or pathlib.Path.home() / "src/goldbox-codewheel")


def normalise(points: set[tuple[int, int]]) -> frozenset[tuple[int, int]]:
    """Ink scaled into a `GRID` x `GRID` box by its own bounding box.

    Two renderings of the same rune differ in size, in stroke width and in
    how much of the outline the emboss lights, so nothing survives a pixel
    comparison.  What does survive is where the ink is relative to the glyph's
    own extent, which is what this keeps.
    """
    if not points:
        return frozenset()
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = max(1, x1 - x0 + 1), max(1, y1 - y0 + 1)
    return frozenset(((x - x0) * GRID // w, (y - y0) * GRID // h)
                     for x, y in points)


def near(a: frozenset, b: frozenset, radius: int = 1) -> float:
    """What fraction of `a` has a point of `b` within `radius` cells."""
    if not a:
        return 0.0
    return sum(any((x + dx, y + dy) in b
                   for dx in range(-radius, radius + 1)
                   for dy in range(-radius, radius + 1))
               for x, y in a) / len(a)


def score(a: frozenset, b: frozenset) -> float:
    """How alike two normalised grids are, 1.0 being identical.

    **Not an overlap count.**  The screen glyph is a filled emboss and the
    reference is a one-pixel outline, so a strict intersection scores the
    right rune no better than the wrong one -- measured on the first frame
    this was run against, where the correct pair came 2nd and 6th at 0.31 and
    0.41.  Allowing a cell of slack in both directions puts them 1st at 0.96
    and 0.98, three points clear of the runner-up.
    """
    return 0.5 * near(a, b) + 0.5 * near(b, a)


def declutter(points: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """Drop pixels with fewer than two neighbours: the tile's own edge dirt."""
    return {p for p in points
            if sum(((p[0] + dx, p[1] + dy) in points)
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1)) >= 3}


def tile_ink(im, box: tuple[int, int, int, int]) -> set[tuple[int, int]]:
    px = im.load()
    left, top, w, h = box
    return declutter({(x, y) for y in range(top, top + h)
                      for x in range(left, left + w)
                      if px[x, y] not in BACKGROUND})


def reference(pre: str, n: int) -> list[frozenset]:
    from PIL import Image  # noqa: PLC0415

    out = []
    for i in range(n):
        path = wheel_repo() / "coab" / "images" / f"{pre}{i:02d}.png"
        im = Image.open(path).convert("L")
        w, h = im.size
        px = im.load()
        out.append(normalise({(x, y) for y in range(h) for x in range(w)
                              if px[x, y] < 128}))
    return out


def path_marks(im, top: int) -> list[tuple[int, int, tuple[int, ...]]]:
    """The horizontal marks in the 8-pixel text cell starting at row `top`.

    A dash and a dot are each **two rows tall and several columns wide**, and
    no letter in the game's font is: a letter's columns light five or six
    rows.  So a run of four or more consecutive columns whose lit rows are the
    same adjacent pair is a mark and everything else is text, which is what
    separates the pattern from the words `UNDER THE` and `PATH.` around it.
    """
    px = im.load()
    cols = {x: tuple(y - top for y in range(top, top + 8)
                     if sum(px[x, y]) > 150) for x in range(320)}
    out, x = [], 0
    while x < 320:
        rows = cols[x]
        if len(rows) == 2 and rows[1] == rows[0] + 1:
            j = x
            while j < 320 and cols[j] == rows:
                j += 1
            if j - x >= 4:
                out.append((x, j, rows))
            x = j
        else:
            x += 1
    return out


def read_path(im) -> int | None:
    """Which of the three patterns is drawn, by where in its cell each mark sits.

    A dash is drawn across the middle of its cell and a dot along the bottom.
    All-middle is `----------`, all-bottom is `..........`, and both heights
    in one row is the mixed `-..-..-..-`.
    """
    for cell in range(8, 24):
        marks = path_marks(im, cell * 8)
        if len(marks) < 3:
            continue
        heights = {rows[0] for _a, _b, rows in marks}
        if heights <= {2, 3}:
            return 0
        if min(heights) >= 4:
            return 1
        return 2
    return None


def identify(shot: pathlib.Path) -> dict:
    from PIL import Image  # noqa: PLC0415

    im = Image.open(shot).convert("RGB")
    if im.size != (320, 200):
        im = im.resize((320, 200), Image.NEAREST)
    out: dict = {}
    for name, box, pre, count in (
            ("espruar", TILES["espruar"], "esp", 26),
            ("dethek", TILES["dethek"], "det", 22)):
        ink = tile_ink(im, box)
        got = normalise(ink)
        refs = reference(pre, count)
        ranked = sorted(((score(got, r), i) for i, r in enumerate(refs)),
                        reverse=True)
        out[name] = ranked
        out[name + "_ink"] = len(ink)
    out["path"] = read_path(im)
    return out


def answer(box: int, espruar: int, dethek: int, path: int) -> tuple[str, str]:
    sys.path.insert(0, str(wheel_repo() / "coab" / "analysis"))
    import wheel  # noqa: PLC0415

    row = 6 - box
    return wheel.answer(row, espruar, dethek, path), \
        wheel.dos_answer(row, espruar, dethek, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shot", required=True, help="a 320x200 frame of the prompt")
    ap.add_argument("--box", type=int, default=None,
                    help="the box number the prompt printed, 1-6")
    ap.add_argument("--path", type=int, default=None, choices=(0, 1, 2),
                    help="override the path this reads off the frame")
    ap.add_argument("--top", type=int, default=4,
                    help="how many rune candidates to print")
    args = ap.parse_args(argv)
    got = identify(pathlib.Path(args.shot))
    # **A frame that is not the prompt still scores.**  The matcher normalises
    # whatever ink it finds, so a main menu answers a rune with a confident
    # number and no warning; Curse does not ask its wheel on every boot, so a
    # driver *will* meet that frame.  Both tiles hold 100 or more pixels on a
    # real prompt and a handful on anything else.
    if min(got["espruar_ink"], got["dethek_ink"]) < 40 or got["path"] is None:
        print(f"this frame does not look like the code-wheel prompt: "
              f"{got['espruar_ink']} and {got['dethek_ink']} pixels in the "
              f"rune tiles, path {got['path']}")
        return 1
    for name in ("espruar", "dethek"):
        best = got[name][:args.top]
        print(f"{name:8s} " + "  ".join(f"{i}={s:.2f}" for s, i in best))
    path = args.path if args.path is not None else got["path"]
    print("path    ", path, PATH_NAMES[path] if path is not None else "(unread)")
    if args.box is None or path is None:
        print("pass --box (and --path if the reading above is wrong) "
              "for the answer")
        return 0
    e, d = got["espruar"][0][1], got["dethek"][0][1]
    c64, dos = answer(args.box, e, d, path)
    print(f"box {args.box}, espruar {e}, dethek {d}, path {path}: "
          f"type {dos!r} on DOS ({c64!r} on the C64)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
