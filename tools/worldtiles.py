#!/usr/bin/env python3
"""Draw Pool of Radiance's wilderness tiles the way the C64 draws them.

Measurement A of `docs/217-drawing-the-wilderness.md`, for
`#11 (Draw the wilderness on the automapper)`: the overland map is a byte a
square indexing 120 tile pictures, and until somebody looks at the pictures
nobody can say which square is a hill and which is a mountain.  This renders
them off the player's own disks.

**The pictures are the game's art and are never committed.**  The tool is;
the PNGs it writes go under `--out`, which defaults to `work/issue11/`.

## What a tile is

`goldbox/world.py` reads a `SQRDATA0n` file: 648 bytes of 18 x 36 grid, then
120 entries of 18 bytes, nine screen codes then nine colour attributes -- a
3 x 3 block of characters.  This module adds the three things that turn those
numbers into pixels:

* **the glyphs.** `SECSET04`/`05`/`06` ride `POOL6`/`7`/`8` beside their own
  window's `SQRDATA`, 1536 bytes = 192 glyphs of eight bytes.  Every screen
  code in every tile any of the three grids uses lies in `$40`-`$FE`, so the
  glyph is `code - $40`.
* **the mode.** Bit 3 of a colour attribute selects multicolour on a C64, and
  most of these have it set.  A multicolour cell draws in pixel *pairs*: `00`
  the background `$D021`, `01` `$D022`, `10` `$D023`, `11` the cell's own
  colour, which is the low nibble with bit 3 taken off.  A hi-res cell draws
  its own colour on the background.
* **the shared colours.**  Three of a multicolour cell's four colours are
  the same for the whole screen, so they are not in the file at all.
  `SHARED` below carries them, measured on the machine.

The attribute's **high nibble** is not the C64's business: colour RAM is four
bits wide and the chip never sees it.  `census` counts it; what the engine
does with it is not settled here.

    tools/worldtiles.py sheet --window all
    tools/worldtiles.py view 5 7 29 --scale 4
    tools/worldtiles.py codes 5 7 29
    tools/worldtiles.py census
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox import world as W  # noqa: E402
from goldbox.d64 import D64, load_payload  # noqa: E402

#: The C64's sixteen colours, the same table `tools/cursepic.py` draws its
#: Curse pictures with -- one palette for the project rather than two that
#: disagree by a few units of blue.
PALETTE = [
    (0, 0, 0), (255, 255, 255), (136, 0, 0), (170, 255, 238),
    (204, 68, 204), (0, 204, 85), (0, 0, 170), (238, 238, 119),
    (221, 136, 85), (102, 68, 0), (255, 119, 119), (51, 51, 51),
    (119, 119, 119), (170, 255, 102), (0, 136, 255), (187, 187, 187),
]

#: Every screen code in every tile the three grids use is `$40` or above, and
#: the set holds 192 glyphs, so this is the offset from code to glyph.
GLYPH_BASE = 0x40
GLYPH_BYTES = 8
CHARSET_GLYPHS = 192

#: A tile is 3 x 3 characters.
TILE_CELLS = 3
TILE_PIXELS = TILE_CELLS * 8

#: The wilderness charsets, one a window, in `WINDOW_NAMES` order.
CHARSET_NAMES = ("SECSET04", "SECSET05", "SECSET06")

#: `$D021`, `$D022`, `$D023` -- the three colours a multicolour cell shares
#: with the whole screen, so no tile can carry them: black, light grey and
#: green.  **Read off the chip on the travel grid**, 2026-09-08, measurement
#: B of `docs/217-drawing-the-wilderness.md`: `tools/worldregisters.py` booted
#: `work/p190/C64OUT1.D64` and read `$D021`-`$D023` as `$F0 $FF $F5` while the
#: party stood at (8,27) on the middle window, the border `$D020` black with
#: it.  Change this only against another such reading -- fitting it to a
#: screenshot is how the plains came to be called light grey in
#: `docs/137-wilderness-automap.md`.
SHARED = (0x00, 0x0F, 0x05)


def disks_dir() -> pathlib.Path:
    """The player's disks: `$POR_DISKS`, then the registry, and never a path
    written here."""
    where = os.environ.get("POR_DISKS") or find_disks()
    if not where:
        raise SystemExit("No Pool of Radiance disks: set $POR_DISKS.")
    return pathlib.Path(where)


def images(root: pathlib.Path) -> list[D64]:
    return [D64.open(p) for p in sorted(root.glob("POOL?.D64"))]


def charset(disks: list[D64], index: int) -> bytes:
    """`SECSET0n`'s 192 glyphs, from whichever disk carries it.

    The `SECSET` PRG header's load address is not where the game runs it
    (`docs/140-loaded-files-cache.md`), so the two bytes are dropped and the
    glyphs are indexed from zero.
    """
    name = CHARSET_NAMES[index].encode()
    for image in disks:
        if image.find(name) is not None:
            payload = load_payload(image, name)
            if len(payload) < CHARSET_GLYPHS * GLYPH_BYTES:
                raise SystemExit(
                    f"{CHARSET_NAMES[index]} is {len(payload)} bytes, "
                    f"short of {CHARSET_GLYPHS * GLYPH_BYTES}")
            return payload
    raise SystemExit(f"no disk here carries {CHARSET_NAMES[index]}")


def cell_pixels(glyph: bytes, attribute: int,
                shared: tuple[int, int, int] = SHARED) -> list[list[int]]:
    """One character cell as 8 x 8 colour indices, rows top to bottom.

    Bit 3 of `attribute` selects multicolour, which is the whole of the
    difference between the two branches: a multicolour row is four pixel
    pairs out of a four-colour choice, a hi-res row eight pixels out of two.
    """
    colour = attribute & 0x0F
    background, mc1, mc2 = shared
    out = []
    for row in range(8):
        bits = glyph[row]
        line = []
        if colour & 0x08:
            choice = (background, mc1, mc2, colour & 0x07)
            for pair in range(4):
                value = (bits >> (6 - pair * 2)) & 0x03
                line.append(choice[value])
                line.append(choice[value])
        else:
            for bit in range(8):
                line.append(colour if (bits >> (7 - bit)) & 1 else background)
        out.append(line)
    return out


def tile_pixels(tile: W.Tile, glyphs: bytes,
                shared: tuple[int, int, int] = SHARED) -> list[list[int]]:
    """One tile as 24 x 24 colour indices."""
    rows = [[0] * TILE_PIXELS for _ in range(TILE_PIXELS)]
    for cell in range(9):
        code = tile.screen_codes[cell]
        at = (code - GLYPH_BASE) * GLYPH_BYTES
        glyph = glyphs[at:at + GLYPH_BYTES] if at >= 0 else bytes(8)
        pixels = cell_pixels(glyph, tile.attributes[cell], shared)
        cx, cy = (cell % TILE_CELLS) * 8, (cell // TILE_CELLS) * 8
        for y in range(8):
            for x in range(8):
                rows[cy + y][cx + x] = pixels[y][x]
    return rows


def image_of(pixels: list[list[int]], scale: int = 1):
    """A `PIL.Image` from a grid of colour indices."""
    from PIL import Image
    height, width = len(pixels), len(pixels[0])
    im = Image.new("RGB", (width, height))
    put = im.putpixel
    for y, row in enumerate(pixels):
        for x, index in enumerate(row):
            put((x, y), PALETTE[index])
    if scale != 1:
        im = im.resize((width * scale, height * scale), Image.NEAREST)
    return im


def used_counts(window: W.Window) -> collections.Counter:
    """How many grid squares each tile index is drawn on."""
    return collections.Counter(window.square(x, y)
                               for y in range(W.ROWS) for x in range(W.STRIDE))


def pane(window: W.Window, glyphs: bytes, left: int, top: int,
         across: int, down: int, shared=SHARED) -> list[list[int]]:
    """The tiles of a rectangle of grid squares, as one picture."""
    rows = [[0] * (across * TILE_PIXELS) for _ in range(down * TILE_PIXELS)]
    for j in range(down):
        for i in range(across):
            x, y = left + i, top + j
            if not (0 <= x < W.STRIDE and 0 <= y < W.ROWS):
                continue
            block = tile_pixels(window.tile_at(x, y), glyphs, shared)
            for py in range(TILE_PIXELS):
                for px in range(TILE_PIXELS):
                    rows[j * TILE_PIXELS + py][i * TILE_PIXELS + px] = \
                        block[py][px]
    return rows


def pane_codes(window: W.Window, left: int, top: int,
               across: int, down: int) -> list[list[tuple[int, int]]]:
    """The character codes and attributes a pane would put on the screen.

    One row a character row, `(screen code, attribute)` a cell -- what
    `tools/worldregisters.py` compares against the live screen and colour
    RAM, which is the check that says the 9-and-9 split and the pane
    geometry are both right.
    """
    out = []
    for j in range(down):
        for cell_row in range(TILE_CELLS):
            row = []
            for i in range(across):
                x, y = left + i, top + j
                if not (0 <= x < W.STRIDE and 0 <= y < W.ROWS):
                    row.extend([(0, 0)] * TILE_CELLS)
                    continue
                tile = window.tile_at(x, y)
                for cell_col in range(TILE_CELLS):
                    at = cell_row * TILE_CELLS + cell_col
                    row.append((tile.screen_codes[at], tile.attributes[at]))
            out.append(row)
    return out


# -- commands ---------------------------------------------------------------

def _windows(args):
    root = disks_dir()
    disks = images(root)
    world = W.World.from_disks(disks)
    wanted = (0, 1, 2) if args.window in (None, "all") else \
        (int(args.window) - 4,)
    for index in wanted:
        yield index, world.windows[index], charset(disks, index)


def _shared(args) -> tuple[int, int, int]:
    if not args.shared:
        return SHARED
    parts = [int(p, 0) & 0x0F for p in args.shared.replace(",", " ").split()]
    if len(parts) != 3:
        raise SystemExit("--shared takes three colours: $D021,$D022,$D023")
    return tuple(parts)                                     # type: ignore


def cmd_sheet(args) -> int:
    from PIL import Image, ImageDraw
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shared = _shared(args)
    scale = args.scale
    label = 10
    columns = args.columns
    for index, window, glyphs in _windows(args):
        counts = used_counts(window)
        rows = (W.TILE_COUNT + columns - 1) // columns
        cell = TILE_PIXELS * scale
        pitch_x, pitch_y = cell + 8, cell + label + 8
        sheet = Image.new("RGB", (columns * pitch_x, rows * pitch_y),
                          (32, 32, 32))
        draw = ImageDraw.Draw(sheet)
        for tile in range(W.TILE_COUNT):
            picture = image_of(tile_pixels(window.tile(tile), glyphs, shared),
                               scale)
            cx = (tile % columns) * pitch_x + 4
            cy = (tile // columns) * pitch_y + 4
            sheet.paste(picture, (cx, cy))
            draw.text((cx, cy + cell), f"{tile} x{counts.get(tile, 0)}",
                      fill=(200, 200, 200))
        name = out / f"tiles-{W.WINDOW_NAMES[index].lower()}.png"
        sheet.save(name)
        print(f"{name}: {W.TILE_COUNT} tiles, "
              f"{len(counts)} of them used by the grid")
    return 0


def cmd_view(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shared = _shared(args)
    left = args.x - args.across // 2
    top = args.y - args.down // 2
    for index, window, glyphs in _windows(args):
        picture = image_of(pane(window, glyphs, left, top,
                                args.across, args.down, shared), args.scale)
        name = out / (f"view-{W.WINDOW_NAMES[index].lower()}"
                      f"-{args.x}-{args.y}.png")
        picture.save(name)
        print(f"{name}: {args.across}x{args.down} tiles at "
              f"({left},{top}), party square ({args.x},{args.y})")
    return 0


def cmd_codes(args) -> int:
    left = args.x - args.across // 2
    top = args.y - args.down // 2
    for index, window, _glyphs in _windows(args):
        print(f"{W.WINDOW_NAMES[index]} pane at ({left},{top}), "
              f"{args.across}x{args.down} tiles:")
        for row in pane_codes(window, left, top, args.across, args.down):
            print("  " + " ".join(f"{c:02X}/{a:02X}" for c, a in row))
    return 0


def cmd_census(args) -> int:
    """The numbers `docs/217`'s table rests on, re-takeable."""
    for index, window, glyphs in _windows(args):
        counts = used_counts(window)
        codes: collections.Counter = collections.Counter()
        low: collections.Counter = collections.Counter()
        high: collections.Counter = collections.Counter()
        for tile in sorted(counts):
            entry = window.tile(tile)
            codes.update(entry.screen_codes)
            low.update(a & 0x0F for a in entry.attributes)
            high.update(a >> 4 for a in entry.attributes)
        print(f"{W.WINDOW_NAMES[index]}: {len(counts)} of {W.TILE_COUNT} "
              f"tiles used, highest index {max(counts)}")
        print(f"  screen codes ${min(codes):02X}-${max(codes):02X}, "
              f"{len(codes)} distinct; glyphs in the set {CHARSET_GLYPHS}, "
              f"{len(glyphs) // GLYPH_BYTES} read")
        print("  attribute low nibbles (the colour): " + ", ".join(
            f"${k:X} x{v}" for k, v in sorted(low.items())))
        print("  attribute high nibbles (not the chip's): " + ", ".join(
            f"${k:X} x{v}" for k, v in sorted(high.items())))
        multi = sum(v for k, v in low.items() if k & 8)
        print(f"  multicolour cells {multi} of {sum(low.values())}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default="work/issue11",
                   help="where the PNGs go; the game's art never leaves it")
    p.add_argument("--window", default="all", help="4, 5, 6 or all")
    p.add_argument("--shared", default="",
                   help="$D021,$D022,$D023, overriding the measured SHARED")
    sub = p.add_subparsers(dest="command", required=True)

    sheet = sub.add_parser("sheet", help="every tile of a window, labelled")
    sheet.add_argument("--scale", type=int, default=3)
    sheet.add_argument("--columns", type=int, default=12)
    sheet.set_defaults(func=cmd_sheet)

    for name, func in (("view", cmd_view), ("codes", cmd_codes)):
        one = sub.add_parser(name, help="the game's own pane around a square")
        one.add_argument("x", type=int)
        one.add_argument("y", type=int)
        one.add_argument("--across", type=int, default=5)
        one.add_argument("--down", type=int, default=5)
        one.add_argument("--scale", type=int, default=3)
        one.set_defaults(func=func)

    census = sub.add_parser("census", help="the tile and attribute counts")
    census.set_defaults(func=cmd_census)

    args = p.parse_args(argv)
    if args.command in ("view", "codes") and args.window == "all":
        args.window = "5"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
