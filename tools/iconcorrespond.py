#!/usr/bin/env python3
"""Lay the two ports' combat-icon art side by side and score the pairing (#130).

The question `#130 (A converted DOS party arrives with six identical combat
figures, not its own)` opens with is whether DOS body `n` is C64 weapon `n`.
If it is, carrying the icon is a table lookup; if it is not, somebody has to
decide which C64 figure each DOS one becomes, and that is not an agent's
decision to make.

So this tool answers it by measurement rather than by argument.  It reads

* the DOS art out of `CHEAD.DAX` and `CBODY.DAX` in the player's own game
  directory -- 4-bit EGA pixels, `17 + rows * stride` bytes a block, the same
  reader `tools/portraitshot.py` uses for the sheet portraits;
* the C64 art out of `SPELLE64`, `SPELLN64` and `CHARPIC00` on `POOL3.D64`,
  through `goldbox.iconparts`, which composes one menu option at a time onto
  an otherwise empty shape;

renders both to a 24x24 ink mask, and scores every DOS option against every
C64 option.  A C64 cell drawn in multicolour has four double-width pixels to
the row rather than eight, so the C64 mask is coarser across than the DOS
one; the score is a Jaccard overlap searched over a small alignment window
(+/-2 rows, +/-1 column) so that a one-pixel difference in where a figure
sits cannot pass for a difference in what it is.

Nothing here is a conversion and nothing here writes.  The output is counts,
scores and -- with `--catalogue` or `--show` -- ASCII pictures of art that
stays on the player's own disks.

Usage:

    tools/iconcorrespond.py                     # the counts and the scores
    tools/iconcorrespond.py --catalogue dos     # every DOS body, as ASCII
    tools/iconcorrespond.py --show 72           # DOS body 72 beside its match
    tools/iconcorrespond.py --png work/sheet.png    # both lists, in colour

The `--png` contact sheet is the one output meant for a person rather than
for a grep: whichever C64 figure each DOS one should become is a decision
about what a converted character looks like, and nobody can make it off a
Jaccard score.  It draws each option as the game itself would -- the DOS
figures in EGA with the art's own stored colours, the C64 ones in the
combat floor's four -- and writes a PNG **under `work/`**, which is
gitignored, because it is the game's art.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.paths import find_disks  # noqa: E402
from goldbox import icons  # noqa: E402
from goldbox.dos_savegame import dax_blocks  # noqa: E402
from goldbox.iconparts import CELLS_PER_POSE, SPACE, IconParts  # noqa: E402

#: A block's pixels start here.  Byte 0 is the row count and byte 2 the width
#: in fours; `tools/portraitshot.py` fitted the 17 against every `HEAD`,
#: `BODY`, `CHEAD` and `CBODY` block in the game.
PIXEL_START = 17

#: The figure both ports draw: three cells across, three down, eight pixels a
#: cell.  The DOS blocks are 24 wide too -- `block[2] * 4 * 2`.
FIGURE = 24

#: Which `.DAX` block ids carry which size.  Bit 6 picks the size and bit 7
#: the pose: `CBODY` holds 32 bodies at 0-31, 64-95, 128-159 and 192-223, and
#: `CHEAD` 14 heads at 0-13, 64-77, 128-141 and 192-205.  Ten of the small
#: group's rows are blank where its taller head goes, eight of the large
#: group's, which is what says which way round the two are.
POSE_BIT = 0x80
SIZE_BIT = 0x40

#: How far the alignment search looks.  Two rows and one column: enough to
#: absorb the ports drawing a figure a pixel apart, not enough to slide one
#: weapon onto another.
SEARCH_ROWS = range(-2, 3)
SEARCH_COLS = range(-1, 2)


# -- the art ----------------------------------------------------------------
def dos_pixels(block: bytes) -> list[list[int]]:
    """One `.DAX` image block as EGA palette indices, `[y][x]`."""
    rows, stride = block[0], block[2] * 4
    out = []
    for y in range(rows):
        line: list[int] = []
        for x in range(stride):
            byte = block[PIXEL_START + y * stride + x]
            line.append(byte >> 4)
            line.append(byte & 0x0F)
        out.append(line)
    return out


def dos_options(game: pathlib.Path, stem: str, size: str,
                pose: int = 0) -> dict[int, list[list[int]]]:
    """Every DOS option of one size and pose, keyed by its menu index."""
    path = game / f"{stem}.DAX"
    want = (POSE_BIT if pose else 0) | (0 if size == "small" else SIZE_BIT)
    out = {}
    for block, raw in dax_blocks(path.read_bytes(), path.name):
        if block & (POSE_BIT | SIZE_BIT) == want:
            out[block & ~(POSE_BIT | SIZE_BIT)] = dos_pixels(raw)
    return out


def c64_option(parts: IconParts, charset: bytes, size: str, kind: str,
               option: int, pose: int = 0) -> list[list[int]]:
    """One C64 menu option drawn onto an empty shape, as an ink mask."""
    blank = bytes([SPACE] * (CELLS_PER_POSE * 2))
    shape = parts.apply(blank, size, kind, option)
    out = [[0] * FIGURE for _ in range(FIGURE)]
    for i in range(CELLS_PER_POSE):
        glyph = shape[pose * CELLS_PER_POSE + i]
        multi = parts.multicolour(glyph)
        cx, cy = i % 3, i // 3
        bitmap = charset[glyph * 8:glyph * 8 + 8]
        for row in range(8):
            bits = bitmap[row] if row < len(bitmap) else 0
            if multi:
                for pair in range(4):
                    ink = 1 if (bits >> (6 - pair * 2)) & 0x03 else 0
                    out[cy * 8 + row][cx * 8 + pair * 2] = ink
                    out[cy * 8 + row][cx * 8 + pair * 2 + 1] = ink
            else:
                for bit in range(8):
                    out[cy * 8 + row][cx * 8 + bit] = (bits >> (7 - bit)) & 1
    return out


# -- comparing them ---------------------------------------------------------
def mask(pixels: list[list[int]]) -> list[list[int]]:
    """A 24x24 ink mask from either port's rendering: non-background is ink."""
    out = [[0] * FIGURE for _ in range(FIGURE)]
    for y, row in enumerate(pixels[:FIGURE]):
        for x, value in enumerate(row[:FIGURE]):
            out[y][x] = 1 if value else 0
    return out


def overlap(a: list[list[int]], b: list[list[int]], dy: int, dx: int) -> float:
    """Jaccard overlap of two masks with `b` shifted by `(dy, dx)`."""
    inter = union = 0
    for y in range(FIGURE):
        for x in range(FIGURE):
            left = a[y][x]
            yy, xx = y + dy, x + dx
            right = b[yy][xx] if 0 <= yy < FIGURE and 0 <= xx < FIGURE else 0
            inter += left and right
            union += left or right
    return inter / union if union else 0.0


def best_overlap(a: list[list[int]], b: list[list[int]]) -> float:
    return max(overlap(a, b, dy, dx)
               for dy in SEARCH_ROWS for dx in SEARCH_COLS)


def ascii_art(pixels: list[list[int]]) -> list[str]:
    return [''.join('#' if v else '.' for v in row) for row in pixels]


# -- where the files are ----------------------------------------------------
def dos_game(given: str | None) -> pathlib.Path:
    """The DOS game directory: `--dos`, then `$POR_DOS_GAME`, then a search."""
    if given:
        return pathlib.Path(given).expanduser()
    named = os.environ.get("POR_DOS_GAME")
    if named:
        return pathlib.Path(named).expanduser()
    roots = [pathlib.Path.home() / "dos_por_play"]
    archives = os.environ.get("FR_ARCHIVES")
    if archives:
        roots += sorted(pathlib.Path(archives).expanduser().rglob("POOLRAD"))
    for root in roots:
        if (root / "CBODY.DAX").exists() and (root / "CHEAD.DAX").exists():
            return root
    raise SystemExit(
        "no DOS Pool of Radiance directory with CBODY.DAX and CHEAD.DAX in "
        "it; pass --dos, or set POR_DOS_GAME")


def c64_disk(given: str | None) -> pathlib.Path:
    """`POOL3.D64`: `--disk`, then `$POR_DISKS`, then `find_disks()`."""
    if given:
        return pathlib.Path(given).expanduser()
    where = os.environ.get("POR_DISKS") or find_disks()
    if not where:
        raise SystemExit("no C64 disks; pass --disk, or set POR_DISKS")
    return pathlib.Path(where) / "POOL3.D64"


# -- the report -------------------------------------------------------------
def report(game: pathlib.Path, disk: pathlib.Path) -> None:
    parts = IconParts.load(str(disk))
    charset = icons.load_icon_charset(str(disk))
    print(f"DOS  {game}")
    print(f"C64  {disk}\n")
    print("option counts")
    for size in ("small", "large"):
        heads = dos_options(game, "CHEAD", size)
        bodies = dos_options(game, "CBODY", size)
        print(f"  {size:5}  DOS heads {len(heads):3}  bodies {len(bodies):3}"
              f"   C64 heads {parts.count(size, 'head'):3}"
              f"  weapons {parts.count(size, 'weapon'):3}")
    print()
    for size in ("small", "large"):
        for dos_stem, c64_kind in (("CBODY", "weapon"), ("CHEAD", "head")):
            score_set(parts, charset, game, size, dos_stem, c64_kind)


def score_set(parts: IconParts, charset: bytes, game: pathlib.Path, size: str,
              dos_stem: str, c64_kind: str) -> None:
    """How often DOS option `n` is the C64 option `n` looks most like."""
    dos = {n: mask(px) for n, px in dos_options(game, dos_stem, size).items()}
    count = parts.count(size, c64_kind)
    c64 = {o: mask(c64_option(parts, charset, size, c64_kind, o))
           for o in range(count)}
    identity = 0
    bests = []
    lines = []
    for n in sorted(dos):
        # Ties broken towards the lower option number, so that the count
        # below is a property of the art rather than of the sort.
        ranked = sorted(((best_overlap(dos[n], c64[o]), o) for o in c64),
                        key=lambda pair: (-pair[0], pair[1]))
        order = [o for _, o in ranked]
        rank = order.index(n) if n in c64 else None
        identity += rank == 0
        bests.append(ranked[0][0])
        lines.append(f"    DOS {n:3} -> C64 {ranked[0][1]:3} "
                     f"({ranked[0][0]:.3f});  same index ranks "
                     f"{'off the list' if rank is None else rank}")
    print(f"  {size} {dos_stem} against C64 {size} {c64_kind}: "
          f"same index is the best match {identity} of {len(dos)}, "
          f"mean best overlap {sum(bests) / len(bests):.3f}")
    for line in lines:
        print(line)
    print()


def catalogue(game: pathlib.Path, disk: pathlib.Path, which: str, size: str,
              kind: str, rows: int) -> None:
    if which == "dos":
        stem = "CBODY" if kind == "weapon" else "CHEAD"
        art = {n: ascii_art(mask(px))
               for n, px in dos_options(game, stem, size).items()}
    else:
        parts = IconParts.load(str(disk))
        charset = icons.load_icon_charset(str(disk))
        art = {o: ascii_art(c64_option(parts, charset, size, kind, o))
               for o in range(parts.count(size, kind))}
    ids = sorted(art)
    for i in range(0, len(ids), 4):
        group = ids[i:i + 4]
        print(' | '.join(f"{which} {size} {kind} {n:<{FIGURE - 18}}"
                         for n in group))
        for y in range(rows):
            print(' | '.join(art[n][y] for n in group))
        print()


def show(game: pathlib.Path, disk: pathlib.Path, size: str, kind: str,
         dos_index: int, c64_index: int | None) -> None:
    parts = IconParts.load(str(disk))
    charset = icons.load_icon_charset(str(disk))
    stem = "CBODY" if kind == "weapon" else "CHEAD"
    left = mask(dos_options(game, stem, size)[dos_index])
    if c64_index is None:
        c64 = {o: mask(c64_option(parts, charset, size, kind, o))
               for o in range(parts.count(size, kind))}
        c64_index = max(c64, key=lambda o: best_overlap(left, c64[o]))
    right = c64_option(parts, charset, size, kind, c64_index)
    print(f"DOS {size} {stem} {dos_index:<12} | "
          f"C64 {size} {kind} {c64_index}")
    for a, b in zip(ascii_art(left), ascii_art(right)):
        print(f"{a} | {b}")


#: The EGA palette the DOS art is drawn in, as `#rrggbb`.  Same sixteen
#: colours `tools/portraitshot.py` matches captured frames against.
EGA = ("#000000", "#0000AA", "#00AA00", "#00AAAA", "#AA0000", "#AA00AA",
       "#AA5500", "#AAAAAA", "#555555", "#5555FF", "#55FF55", "#55FFFF",
       "#FF5555", "#FF55FF", "#FFFF55", "#FFFFFF")


def _composite(body: list[list[int]], head: list[list[int]]) -> list[list[int]]:
    """A DOS figure: the head block drawn over the body block from row 0."""
    out = [row[:] + [0] * (FIGURE - len(row)) for row in body]
    out += [[0] * FIGURE for _ in range(FIGURE - len(out))]
    for y, row in enumerate(head[:FIGURE]):
        for x, value in enumerate(row[:FIGURE]):
            if value:
                out[y][x] = value
    return out


def _dos_sheet(game: pathlib.Path, size: str, kind: str) -> list[tuple]:
    """Every DOS option of one kind, completed by the other kind's first."""
    bodies = dos_options(game, "CBODY", size)
    heads = dos_options(game, "CHEAD", size)
    if kind == "weapon":
        return [(n, _composite(bodies[n], heads[min(heads)]))
                for n in sorted(bodies)]
    return [(n, _composite(bodies[min(bodies)], heads[n]))
            for n in sorted(heads)]


def _c64_sheet(disk: pathlib.Path, size: str, kind: str) -> list[tuple]:
    """Every C64 option of one kind, drawn the way the combat floor draws it."""
    from goldbox.iconparts import (
        DEFAULT_HEAD,
        DEFAULT_PART_COLOURS,
        DEFAULT_WEAPON,
        MULTICOLOUR,
    )

    parts = IconParts.load(str(disk))
    charset = icons.load_icon_charset(str(disk))
    # The measured default (#57) covers only body, hair, arm and leg: weapon 0
    # is empty hands and head 1 wears nothing, so no weapon, cap or shield
    # colour of the engine's was ever seen.  Those three get a colour here so
    # the sheet shows a weapon at all -- black on black is what the default
    # would draw -- and it is a choice about this picture, not a measurement.
    palette = dict(DEFAULT_PART_COLOURS)
    palette.setdefault(0, 1)            # weapon: white
    palette.setdefault(2, 2)            # cap: red
    palette.setdefault(4, 7)            # shield: yellow
    out = []
    for option in range(parts.count(size, kind)):
        weapon = option if kind == "weapon" else DEFAULT_WEAPON
        head = option if kind == "head" else DEFAULT_HEAD
        shape = parts.compose(size, weapon, head)
        seed = bytes([DEFAULT_PART_COLOURS[1] | MULTICOLOUR] * len(shape))
        colours = parts.colours_for(shape, palette, seed)
        pixels = icons.icon_pixels(icons.Icon(shape + colours), charset)
        out.append((option, [row[:FIGURE] for row in pixels[:FIGURE]]))
    return out


def contact_sheet(game: pathlib.Path, disk: pathlib.Path, size: str, kind: str,
                  path: pathlib.Path, scale: int = 4, across: int = 8) -> None:
    """Both ports' whole option lists, one above the other, as a PNG."""
    from PIL import Image, ImageDraw

    rows = [("DOS", _dos_sheet(game, size, kind), EGA),
            ("C64", _c64_sheet(disk, size, kind),
             tuple(icons.C64_PALETTE))]
    cell = FIGURE * scale
    pad, label = 6, 10
    width = across * (cell + pad) + pad
    height = pad
    for _, sheet, _ in rows:
        lines = (len(sheet) + across - 1) // across
        height += label + lines * (cell + pad + label) + pad
    image = Image.new("RGB", (width, height), "#202020")
    draw = ImageDraw.Draw(image)
    y = pad
    for who, sheet, palette in rows:
        draw.text((pad, y), f"{who} {size} {kind}", fill="#FFFFFF")
        y += label
        for i, (index, pixels) in enumerate(sheet):
            col, row = i % across, i // across
            left = pad + col * (cell + pad)
            top = y + row * (cell + pad + label)
            draw.text((left, top), str(index), fill="#AAAAAA")
            for py, line in enumerate(pixels):
                for px, value in enumerate(line):
                    draw.rectangle(
                        [left + px * scale, top + label + py * scale,
                         left + px * scale + scale - 1,
                         top + label + py * scale + scale - 1],
                        fill=palette[value & 0x0F])
        y += ((len(sheet) + across - 1) // across) * (cell + pad + label) + pad
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"{path}  {image.width}x{image.height}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dos", help="the DOS game directory")
    ap.add_argument("--disk", help="POOL3.D64")
    ap.add_argument("--size", default="large", choices=("small", "large"))
    ap.add_argument("--kind", default="weapon", choices=("weapon", "head"))
    ap.add_argument("--catalogue", choices=("dos", "c64"),
                    help="print one port's whole option list as ASCII")
    ap.add_argument("--rows", type=int, default=13,
                    help="how many rows of each figure to print (default 13)")
    ap.add_argument("--show", type=int, metavar="N",
                    help="print DOS option N beside a C64 one")
    ap.add_argument("--against", type=int, metavar="M",
                    help="which C64 option --show uses; default the best")
    ap.add_argument("--png", metavar="PATH",
                    help="write both lists as a contact sheet, under work/")
    args = ap.parse_args(argv)

    game, disk = dos_game(args.dos), c64_disk(args.disk)
    if args.png:
        contact_sheet(game, disk, args.size, args.kind,
                      pathlib.Path(args.png))
    elif args.catalogue:
        catalogue(game, disk, args.catalogue, args.size, args.kind, args.rows)
    elif args.show is not None:
        show(game, disk, args.size, args.kind, args.show, args.against)
    else:
        report(game, disk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
