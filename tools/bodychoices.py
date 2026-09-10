#!/usr/bin/env python3
"""Draw the three bodies `#480` is a choice between, so it can be decided by
looking.

A player rolls a Pool of Radiance character on DOS or the C64 and gives him
the **eighth** body in the creation menu.  He converts to the Amiga.  The two
menus agree on eleven of twelve positions and differ at position 8, so there
are three pictures the Amiga could end up drawing and the whole question has
been argued in art ids.  Donald, 2026-09-10: *"I have no idea what you're
talking about.  I would need to see screenshots."*

    tools/bodychoices.py                   # work/issue480/480-bodies.png
    tools/bodychoices.py --menu            # and 480-menu.png, both menus
    tools/bodychoices.py --all             # and 480-all.png, every block
    tools/bodychoices.py --out other.png

The three panels, left to right:

* **what the player chose** -- DOS's own art `0x18`, which is what DOS and the
  C64 draw for menu position 8;
* **what writing 8 gives him on the Amiga** -- the Amiga's art `0x05`, which
  is its own eighth body;
* **what writing 33 gives him on the Amiga** -- the Amiga's art `0x18`,
  reached by indexing thirty-three bytes into a twelve-byte table.
  `tools/amigaportraitresolve.py --out-of-range 33` is where that number comes
  from and the resolving routine applies no range check at all.

`--all` is the picture that answers a question the three panels only imply:
whether the drawing DOS shows for position 8 is on the Amiga disk at all.  It
draws every body block each port ships in id order, and the Amiga's `0D`, `18`
and `22` are visibly one repeated picture -- the one DOS calls `22` -- so the
bare chest DOS keeps under `0D` and `18` is in none of the Amiga's twenty-one
blocks.  An id existing on both disks is not the same as a picture existing on
both.

Every picture is rendered from a block of the player's own disk: the DOS
panels from `BODY<n>.DAX` through the EGA palette, the Amiga panels from
`/body.dax` on disk 2 through the thirty-two colour words the Amiga
executable copies into its screen (`tools/amigaportraitmenu.py --palette`).
**Neither is a photograph of the running game's character sheet**, which draws
a head above the body inside a frame, so what is compared here is the art the
engine would fetch rather than the pixels a player would see around it.

Nothing is written but the PNGs named on the command line, and they go under
`work/`, which is gitignored: these are the game's own pictures.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import amiga_dax, portraits  # noqa: E402
from tools import amigaportraitmenu as menu  # noqa: E402

#: Where the picture goes unless the caller says otherwise.
OUT = ROOT / "work" / "issue480" / "480-bodies.png"

#: The value that reaches the Amiga's art `0x18` off the end of the menu
#: table, from `tools/amigaportraitresolve.py --out-of-range`.
PAST_THE_END = 33

#: Menu position 8, one-based, which is the position the two ports disagree on.
POSITION = 8

FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

BACKGROUND = (24, 24, 28)
LABEL = (245, 245, 245)
FOOTNOTE = (160, 160, 168)


def font(size: int, bold: bool = False):
    from PIL import ImageFont

    path = FONTS[0] if bold else FONTS[1]
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def sources(disks=None, dos: str | None = None):
    """`(amiga files, palette, DOS body blocks)` off the player's own disks."""
    roots = [pathlib.Path(disks)] if disks else None
    files = menu.amiga_files(roots)
    missing = [name for name in menu.WANTED if name not in files]
    if missing:
        raise FileNotFoundError(
            f"no Amiga Pool of Radiance disk here carries "
            f"{', '.join(missing)}; set AMIGA_DISKS or pass --disks")
    game = pathlib.Path(dos) if dos else menu.dos_game(None)
    if game is None:
        raise FileNotFoundError(
            "no DOS Pool of Radiance directory found; set FR_ARCHIVES or "
            "pass --dos")
    _at, palette = menu.amiga_palette(files[portraits.AMIGA_PROGRAM][1])
    return files, palette, menu.dos_blocks(game, "BODY")


def amiga_body(files, palette, art_id: int):
    return menu.amiga_image(
        amiga_dax.block(files[portraits.AMIGA_BODY_DAX][1], art_id,
                        portraits.AMIGA_BODY_DAX), palette)


def panels(files, palette, dos):
    """The three candidates, each `(headline, footnote, image)`."""
    chosen = portraits.stored_tables().bodies[POSITION - 1]
    amiga = portraits.stored_tables(port=portraits.AMIGA_PORT).bodies[
        POSITION - 1]
    return [
        ("What you chose",
         f"Drawn by DOS and the C64  ·  body art 0x{chosen:02X}",
         menu.dos_image(dos[chosen])),
        ("What the Amiga gives you",
         f"Drawn by the Amiga  ·  body art 0x{amiga:02X}",
         amiga_body(files, palette, amiga)),
        (f"What writing {PAST_THE_END} gives you",
         f"Drawn by the Amiga  ·  body art 0x{chosen:02X}",
         amiga_body(files, palette, chosen)),
    ]


def fitted(draw, text: str, room: int, size: int, bold: bool = False):
    """The largest of `size` and below at which `text` fits in `room` pixels."""
    while size > 10:
        chosen = font(size, bold)
        if draw.textlength(text, font=chosen) <= room:
            return chosen
        size -= 1
    return font(size, bold)


def three(path: pathlib.Path, files, palette, dos, scale: int = 5) -> None:
    from PIL import Image, ImageDraw

    rows = panels(files, palette, dos)
    width, height = rows[0][2].size
    cell = (width * scale, height * scale)
    gap, margin, top = 32, 32, 102
    sheet = Image.new(
        "RGB",
        (margin * 2 + cell[0] * len(rows) + gap * (len(rows) - 1),
         top + cell[1] + 132), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 24),
              "Pool of Radiance: the eighth body in the creation menu",
              font=font(32, bold=True), fill=LABEL)
    draw.text((margin, 66),
              "Every picture here is an art block off the player's own disks, "
              "not a photograph of a character sheet.",
              font=font(18), fill=FOOTNOTE)
    for n, (headline, note, image) in enumerate(rows):
        left = margin + n * (cell[0] + gap)
        sheet.paste(image.resize(cell, Image.NEAREST), (left, top))
        draw.rectangle([left - 1, top - 1, left + cell[0], top + cell[1]],
                       outline=(70, 70, 78))
        draw.text((left, top + cell[1] + 18), headline,
                  font=fitted(draw, headline, cell[0], 28, bold=True),
                  fill=LABEL)
        draw.text((left, top + cell[1] + 56), note,
                  font=fitted(draw, note, cell[0], 18), fill=FOOTNOTE)
    tail = ("The Amiga's own copy of the body on the left is a different "
            "drawing, so the third panel does not give it back.")
    draw.text((margin, top + cell[1] + 96), tail,
              font=fitted(draw, tail, sheet.size[0] - 2 * margin, 20),
              fill=LABEL)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def every_block(path: pathlib.Path, files, palette, dos, scale: int = 2
                ) -> None:
    """Every body block each port ships, in id order, one port per band.

    This is what says whether a picture is on a disk at all, which is a
    different question from whether an id is: the Amiga's `0D`, `18` and `22`
    are one repeated block, and the drawing DOS keeps under `0D` and `18` is
    in none of the Amiga's twenty-one.
    """
    from PIL import Image, ImageDraw

    ids = sorted(dos)
    across = 7
    down = -(-len(ids) // across)
    first = menu.dos_image(dos[ids[0]])
    cell = (first.size[0] * scale, first.size[1] * scale)
    gap, margin = 10, 14
    band = 28 + down * (cell[1] + 24)
    sheet = Image.new("RGB", (margin * 2 + across * cell[0] +
                              (across - 1) * gap, 16 + 2 * band + 16),
                      BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    at = 14
    for label, drawn in (
            ("DOS, every body block it ships",
             lambda i: menu.dos_image(dos[i])),
            ("The Amiga, every body block it ships",
             lambda i: amiga_body(files, palette, i))):
        draw.text((margin, at), label, font=font(20, bold=True), fill=LABEL)
        at += 28
        for n, art_id in enumerate(ids):
            left = margin + (n % across) * (cell[0] + gap)
            top = at + (n // across) * (cell[1] + 24)
            sheet.paste(drawn(art_id).resize(cell, Image.NEAREST), (left, top))
            draw.rectangle([left - 1, top - 1, left + cell[0], top + cell[1]],
                           outline=(70, 70, 78))
            draw.text((left, top + cell[1] + 4), f"{art_id:02X}",
                      font=font(15), fill=FOOTNOTE)
        at += down * (cell[1] + 24) + 16
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def both_menus(path: pathlib.Path, files, palette, dos, scale: int = 2
               ) -> None:
    """Every body each port's creation menu offers, in menu order."""
    from PIL import Image, ImageDraw

    across = 6
    first = menu.dos_image(dos[portraits.stored_tables().bodies[0]])
    width, height = first.size
    cell = (width * scale, height * scale)
    gap, margin = 12, 28
    band = cell[1] + 30
    sheet = Image.new(
        "RGB",
        (margin * 2 + cell[0] * across + gap * (across - 1),
         74 + 2 * (34 + 2 * band)), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 18),
              "The two menus agree everywhere but the one ringed in yellow.",
              font=font(18), fill=FOOTNOTE)
    at = 46
    for label, ids, drawn in (
            ("DOS and the C64, positions 1 to 12",
             portraits.stored_tables().bodies,
             lambda i: menu.dos_image(dos[i])),
            ("The Amiga, positions 1 to 12",
             portraits.stored_tables(port=portraits.AMIGA_PORT).bodies,
             lambda i: amiga_body(files, palette, i))):
        draw.text((margin, at), label, font=font(24, bold=True), fill=LABEL)
        at += 34
        for n, art_id in enumerate(ids):
            left = margin + (n % across) * (cell[0] + gap)
            top = at + (n // across) * band
            sheet.paste(drawn(art_id).resize(cell, Image.NEAREST), (left, top))
            draw.rectangle([left - 1, top - 1, left + cell[0], top + cell[1]],
                           outline=(70, 70, 78))
            odd = n + 1 == POSITION
            if odd:
                draw.rectangle([left - 3, top - 3, left + cell[0] + 2,
                                top + cell[1] + 2], outline=(240, 190, 60),
                               width=3)
            draw.text((left, top + cell[1] + 8), f"{n + 1}", font=font(16),
                      fill=(240, 190, 60) if odd else FOOTNOTE)
        at += 2 * band + 14
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--disks", help="a folder of Amiga .adf images to use "
                                    "instead of the machine's own list")
    ap.add_argument("--dos", help="the DOS Pool of Radiance game directory")
    ap.add_argument("--out", default=str(OUT),
                    help="where the three-panel picture goes")
    ap.add_argument("--menu", action="store_true",
                    help="also draw both ports' twelve menu bodies in order")
    ap.add_argument("--all", action="store_true",
                    help="also draw every body block each port ships, by id")
    args = ap.parse_args(argv)

    try:
        files, palette, dos = sources(args.disks, args.dos)
    except FileNotFoundError as e:
        print(str(e)[0].upper() + str(e)[1:])
        return 2

    out = pathlib.Path(args.out)
    three(out, files, palette, dos)
    print(f"Wrote {out}")
    for wanted, stem, drawn in ((args.menu, "menu", both_menus),
                                (args.all, "all", every_block)):
        if not wanted:
            continue
        beside = out.with_name(
            out.stem.replace("bodies", stem) + out.suffix)
        drawn(beside, files, palette, dos)
        print(f"Wrote {beside}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
