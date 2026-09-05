#!/usr/bin/env python3
"""Tile the same rectangle out of several screenshots into one picture.

Six character sheets are six frames, and the question `#57 (Convert the
character portrait across ports)` asks of them -- did each character arrive
wearing its own face? -- is answered by looking at them **together**.  Six
separate 1400x1050 emulator frames do not answer it; one strip of six
portraits does, and a face that repeats is then obvious rather than something
somebody has to hold in their head across six files.

    tools/portraitmontage.py work/issue57/c64-slotA/sheet-*.png \
        --rect 535,145,190,245 --out work/issue57/c64-faces.png

`--rect` is `left,top,width,height` in the source image's own pixels, and
`--across` tiles left to right instead of top to bottom.  With no `--rect` the
whole frame is used, which is what a DOS capture wants -- it is 320x200 and
the portrait is a quarter of it.

The output goes under `work/`, which is gitignored: these are the game's own
portraits and they are not committed anywhere.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from PIL import Image


def montage(paths: list[pathlib.Path], rect: tuple[int, int, int, int] | None,
            across: bool, scale: int, gap: int) -> Image.Image:
    tiles = []
    for path in paths:
        im = Image.open(path).convert("RGB")
        if rect:
            left, top, width, height = rect
            im = im.crop((left, top, left + width, top + height))
        if scale != 1:
            im = im.resize((im.width * scale, im.height * scale),
                           Image.NEAREST)
        tiles.append(im)
    if not tiles:
        raise SystemExit("no images")
    if across:
        width = sum(t.width for t in tiles) + gap * (len(tiles) - 1)
        height = max(t.height for t in tiles)
    else:
        width = max(t.width for t in tiles)
        height = sum(t.height for t in tiles) + gap * (len(tiles) - 1)
    out = Image.new("RGB", (width, height), (0, 0, 0))
    at = 0
    for tile in tiles:
        out.paste(tile, (at, 0) if across else (0, at))
        at += (tile.width if across else tile.height) + gap
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("images", nargs="+", help="the frames, in order")
    ap.add_argument("--rect", default=None,
                    help="left,top,width,height to cut from each frame")
    ap.add_argument("--across", action="store_true",
                    help="tile left to right instead of top to bottom")
    ap.add_argument("--scale", type=int, default=1,
                    help="nearest-neighbour magnification")
    ap.add_argument("--gap", type=int, default=4,
                    help="pixels between tiles")
    ap.add_argument("--out", default="work/montage.png")
    args = ap.parse_args(argv)

    rect = None
    if args.rect:
        left, top, width, height = (int(n) for n in args.rect.split(","))
        rect = (left, top, width, height)
    picture = montage([pathlib.Path(p) for p in args.images], rect,
                      args.across, args.scale, args.gap)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    picture.save(out)
    print(f"{out} {picture.width}x{picture.height} "
          f"from {len(args.images)} frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())
