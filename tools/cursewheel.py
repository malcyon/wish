#!/usr/bin/env python3
"""Answer DOS Curse of the Azure Bonds' code wheel from a screenshot, without
recording the challenge or the answer.

Curse asks its wheel before the main menu, so **every** driven DOS Curse
session has to answer it, and an agent that cannot is stopped at the title.
The arithmetic behind the answer is worked out in
`~/src/goldbox-codewheel/coab/notes/copy-protection.md` and computed by that
repository's `coab/analysis/wheel.py`; what was missing was the reading --
turning the frame on screen into the four numbers that function wants.
`CLAUDE.md` keeps that arithmetic in Donald's separate private repository, and
this reaches into it at run time and **records nothing** here -- the shape
`tools/amigacursewheel.py` follows for the Amiga side of the same wheel
(#108, Amiga Curse asks its code wheel, so the title cannot be driven
unattended).

    tools/cursewheel.py --shot 008-wheel.png --box 4

prints `challenge on screen, answered`, `challenge on screen, not answered`
(no `--box` given, or the path could not be read) or `no challenge on
screen`, and nothing else -- neither the rune indices, their scores, the path
nor the character typed, because a handful of real challenge-answer pairs is
exactly what `#108`'s ruling keeps out of this repository. `answer` and
`identify` stay importable, so a driver running in the same process can use
what they compute; only the command line's own printing is restricted.

**The frame.** The prompt draws an Espruar rune above a Dethek one, as two
tiles at (143,31) and (143,63) in the 320x200 frame, embossed in white, red
and yellow with a black shadow over two greens.  Everything in a tile that is
not one of the two greens or the border's two greys is the glyph, and that
mask is enough to tell the 26 Espruar and 22 Dethek runes apart: the reference
bitmaps in `coab/images/` are the same runes rendered from the C64's own
`SECSET10`, so the two are the same shapes in different paint, compared as
normalised grids with a cell of slack rather than pixel for pixel.

**The path** is the row under the runes: `----------`, `..........` or
`-..-..-..-`, drawn as marks one to a character cell, each cell's *own shape*
being what tells a dash from a dot -- a dash is a 7px-wide bar across rows 2-3
of its cell, a dot a 3x3 diamond in rows 4-6, measured off three live prompts
on 2026-09-14 (`#537`).  A dash prompt lights only every other cell of the
nine (14, 16, 18, 20, 22 of the row's forty), not a contiguous run, so what
`read_path()` looks for is a run of five or more marked cells with nothing but
text between them, not five or more marked cells in a row.  That is read here;
the **box number is not**, because it is one 8x8 digit glyph in the game's own
display font and reading it needs a font this tool does not have.  Pass
`--box`, which is the number the prompt prints in words a person can read at a
glance.

The wheel table and the two arithmetics come from
the `codewheel` entry of `gamedisks.yaml` (`$WISH_CODEWHEEL` beats it) --
kept out of this repository deliberately, like the disks.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from tools import gamedisks  # noqa: E402

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
    """The private repository, through the `codewheel` registry entry (#575).

    The first candidate is returned when none exists, so a caller's own "is not
    a directory" message names the place `$WISH_CODEWHEEL` would have to point.
    """
    return gamedisks.where("codewheel")


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


#: A dot is DOS Curse's diamond: no more than 3px in either direction and no
#: more than 5 lit pixels, measured at columns 2-4, rows 4-6 of its cell.
DOT_MAX_SIZE = 3
DOT_MAX_INK = 5

#: A dash is DOS Curse's bar: at least 4px wide and no more than 2px tall,
#: measured 7px wide across rows 2-3 of its cell.  Every letter in the game's
#: font lights at least five rows, so nothing in the surrounding prose can
#: pass this test.
DASH_MIN_WIDTH = 4
DASH_MAX_HEIGHT = 2

#: The fewest marked cells one path band has to carry before it is believed
#: over the green period that ends `PATH.`, which is a lone dot two cells
#: past where a real band ends.  A dash band marks only every other cell of
#: its nine -- 14, 16, 18, 20, 22 -- so this counts *marked* cells within a
#: run of non-text cells, not five marked cells adjacent to one another.
MIN_MARKS = 5


def classify_cell(im, left: int, top: int) -> str:
    """`"empty"`, `"dot"`, `"dash"` or `"text"`, for the 8x8 cell at `left`,
    `top`.

    A dot and a dash are read by the shape of their own ink, not by the pen --
    the pen is white here on every specimen seen, but the game's own prose
    row above is white too, so pen colour tells a mark from nothing rather
    than a mark from a letter.
    """
    px = im.load()
    lit = [(x - left, y - top) for y in range(top, top + 8)
           for x in range(left, left + 8) if sum(px[x, y]) > 150]
    if not lit:
        return "empty"
    xs = [p[0] for p in lit]
    ys = [p[1] for p in lit]
    w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    if w <= DOT_MAX_SIZE and h <= DOT_MAX_SIZE and len(lit) <= DOT_MAX_INK:
        return "dot"
    if w >= DASH_MIN_WIDTH and h <= DASH_MAX_HEIGHT:
        return "dash"
    return "text"


def path_marks(im, top: int) -> list[str]:
    """Each of the row's forty 8-pixel text cells, classified by
    `classify_cell`, for the row starting at `top`."""
    return [classify_cell(im, 8 * cell, top) for cell in range(40)]


def read_path(im) -> int | None:
    """Which of the three patterns is drawn, by the shape of the marks in one
    row of cells.

    A run of `MIN_MARKS` or more marked cells, with nothing but empty cells
    between them and text on both sides, is the pattern; an all-dash run is
    `----------` (0), an all-dot run is `..........` (1), and a run carrying
    both is the mixed `-..-..-..-` (2).  The run rule is what keeps the green
    period after `PATH.` -- the same diamond a dot mark is, six cells past
    where a real band ends -- from being read as a one-mark band.
    """
    for top in range(8 * 8, 24 * 8, 8):
        cells = path_marks(im, top)
        i = 0
        while i < len(cells):
            if cells[i] == "text":
                i += 1
                continue
            j = i
            marks = []
            while j < len(cells) and cells[j] != "text":
                if cells[j] != "empty":
                    marks.append(cells[j])
                j += 1
            if len(marks) >= MIN_MARKS:
                kinds = set(marks)
                if kinds == {"dash"}:
                    return 0
                if kinds == {"dot"}:
                    return 1
                return 2
            i = j
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
    args = ap.parse_args(argv)
    got = identify(pathlib.Path(args.shot))
    # **A frame that is not the prompt still scores.**  The matcher normalises
    # whatever ink it finds, so a main menu answers a rune with a confident
    # number and no warning; Curse does not ask its wheel on every boot, so a
    # driver *will* meet that frame.  Both tiles hold 100 or more pixels on a
    # real prompt and a handful on anything else.  Whether the path itself was
    # read is a different question, asked below -- folding it in here turned
    # "the challenge is up but the path did not read" into "nothing is up at
    # all", which contradicts what this docstring has always promised (#537).
    if min(got["espruar_ink"], got["dethek_ink"]) < 40:
        print("no challenge on screen")
        return 1
    path = args.path if args.path is not None else got["path"]
    if args.box is None or path is None:
        print("challenge on screen, not answered")
        return 0
    e, d = got["espruar"][0][1], got["dethek"][0][1]
    answer(args.box, e, d, path)
    print("challenge on screen, answered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
