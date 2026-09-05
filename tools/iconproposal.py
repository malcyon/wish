#!/usr/bin/env python3
"""The proposed DOS-to-C64 combat-figure table, drawn so it can be judged (#130).

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)` ends in a judgement: which of the C64's weapon and head options
each of the DOS game's 32 bodies and 14 heads becomes.  The two ports draw
the same *kinds* of figure -- an archer, a flail, a sword and shield, a
robed caster -- in different orders and from different art, so no
measurement picks the rows, and the ticket says the choice is Donald's.

This tool holds the **proposal** -- three tables a person can edit -- and
draws every row as the two games would draw it: the DOS figure in its own
record colours on the left, the proposed C64 figure on the right in the
colours the same record converts to.  Nothing here converts a save; when the
tables are approved they move into `goldbox/`, and until then they are a
picture on the issue.

    tools/iconproposal.py --png work/issue130/proposal-weapons.png
    tools/iconproposal.py --kind head --png work/issue130/proposal-heads.png
    tools/iconproposal.py --colours 91a2b3c4e6f7      # a record's own six bytes
    tools/iconproposal.py                             # the tables, as text

The DOS side is read the way `tools/iconcorrespond.py` reads it, off the
player's own `CHEAD.DAX`/`CBODY.DAX`; the C64 side is composed by
`goldbox.iconparts` from `POOL3.D64`.  The PNG is the game's art and goes
under `work/`, never into the repository.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import iconcorrespond as ic  # noqa: E402

from goldbox import icons  # noqa: E402
from goldbox.iconparts import MULTICOLOUR, PART_CLASSES, IconParts  # noqa: E402

# -- the proposal -------------------------------------------------------------
#
# DOS body n -> C64 large weapon option.  The C64's small list is the same 28
# designs in the same order (18 of 28 share their weapon glyphs exactly and
# the other ten differ only in the shield glyph the smaller body wears), so
# one table serves both sizes; an option at or above 28 on a small character
# is composed as a large weapon under a small head, which the game accepts
# (HOGARTH's icon on the player's own disks is such a mix).
#
# Every row is a look at `work/issue130/big-*.png`, not a measurement.  The
# rows marked in ALTERNATIVES are the ones where a second option looked as
# close, and the rows *not* marked are the ones where the weapon is
# unmistakable in both ports.
WEAPONS: dict[int, int] = {
    0: 0,       # empty hands
    1: 26,      # bow
    2: 5,       # hammer raised
    3: 23,      # flail swung
    4: 24,      # flail and shield
    5: 21,      # spear thrust level
    6: 27,      # mace raised
    7: 1,       # sword raised
    8: 25,      # sling
    9: 8,       # axe raised
    10: 10,     # war hammer held level
    11: 23,     # flail hanging
    12: 27,     # morning star raised
    13: 27,     # mace, round head
    14: 15,     # hammer, level
    15: 7,      # hatchet
    16: 28,     # crossbow
    17: 14,     # spear held high, thrust in pose 2
    18: 11,     # halberd
    19: 13,     # polearm across the body
    20: 17,     # mace and shield
    21: 6,      # spear and shield
    22: 9,      # axe and shield
    23: 12,     # hammer and shield
    24: 3,      # sword and shield
    25: 22,     # sling and shield -- the C64 has no such figure
    26: 12,     # hammer and shield
    27: 32,     # robed, hands empty
    28: 31,     # robed, staff upright
    29: 34,     # robed, arms out
    30: 29,     # robed, dagger
    31: 30,     # robed, staff across the body
}

WEAPON_ALTERNATIVES: dict[int, tuple[int, ...]] = {
    2: (27,), 5: (14,), 6: (5,), 8: (19,), 11: (25,), 12: (5,), 13: (5,),
    14: (10,), 15: (11,), 17: (2,), 18: (13,), 19: (4,), 20: (12,),
    21: (20,), 23: (24,), 25: (24,), 26: (17,), 27: (34,), 29: (32,),
}

# DOS head n -> C64 large head option.  The C64 small list is 14 heads and
# its large list 23; the DOS small heads are the large designs eight rows
# tall instead of ten.  These rows are the least certain of the three tables:
# a head is two cells of art on the C64 and ten rows on DOS, and half of them
# differ by one band of pixels.
HEADS: dict[int, int] = {
    0: 7,       # short hair
    1: 11,      # headband
    2: 16,      # plumed helmet
    3: 3,       # visored helmet
    4: 8,       # cap over hair
    5: 5,       # hair to the shoulder
    6: 14,      # tall pointed hat
    7: 11,      # headband
    8: 17,      # long hair down the back
    9: 12,      # long hair
    10: 10,     # banded helmet
    11: 6,      # bald
    12: 0,      # close helmet
    13: 13,     # crest
}

HEAD_ALTERNATIVES: dict[int, tuple[int, ...]] = {
    0: (1,), 1: (3,), 2: (15, 22), 3: (15,), 4: (21, 0), 6: (2, 9),
    8: (12,), 9: (17,), 10: (15,), 12: (2,), 13: (16,),
}

#: EGA index -> C64 colour 0-7, the proposal of the colour comment on the
#: issue.  Four of these are not the nearest colour by RGB: brown to yellow,
#: light grey to white, dark grey to black and light red to red.
EGA_TO_C64: tuple[int, ...] = (
    0,  # black
    6,  # blue
    5,  # green
    3,  # cyan
    2,  # red
    4,  # magenta -> purple
    7,  # brown -> yellow
    1,  # light grey -> white
    0,  # dark grey -> black
    6,  # light blue -> blue
    5,  # light green -> green
    3,  # light cyan -> cyan
    2,  # light red -> red
    4,  # light magenta -> purple
    7,  # yellow
    1,  # white
)

#: A DOS hat or plume is drawn in values 5/13, which the character cannot
#: recolour, so it is always magenta; a C64 cap gets purple.
CAP_COLOUR = 4

#: Record bytes `0x0C1`-`0x0C6`, in order, and the C64 part class each one
#: colours.  `goldbox/dos_layout.py` has the running-game measurement.
DOS_PAIR_CLASSES = ("body", "arm", "leg", "hair", "shield", "weapon")

#: The shipped default set, `91 A2 B3 C4 E6 F7`.
DEFAULT_COLOURS = bytes.fromhex("91a2b3c4e6f7")


def c64_part_colours(icon_colours: bytes) -> dict[int, int]:
    """The seven C64 part colours a DOS record's six colour pairs become."""
    out = {PART_CLASSES.index(part): EGA_TO_C64[icon_colours[i] & 0x0F]
           for i, part in enumerate(DOS_PAIR_CLASSES)}
    out[PART_CLASSES.index("cap")] = CAP_COLOUR
    return out


# -- drawing --------------------------------------------------------------------
def dos_recoloured(pixels: list[list[int]], icon_colours: bytes) -> list[list[int]]:
    """A DOS block's part numbers as EGA colours, the way `0x1E55C` does it."""
    lookup = list(range(16))
    for k in range(6):
        lookup[k + 1 if k < 4 else k + 2] = icon_colours[k] & 0x0F
        lookup[(k + 1 if k < 4 else k + 2) + 8] = icon_colours[k] >> 4
    return [[lookup[v] for v in row] for row in pixels]


def c64_figure(parts: IconParts, charset: bytes, size: str, weapon: int,
               head: int, icon_colours: bytes) -> list[list[int]]:
    """Both poses of the proposed C64 figure in the converted colours."""
    weapon_size = "large" if weapon >= parts.count("small", "weapon") else size
    blank = bytes([0x20] * 18)
    shape = parts.apply(blank, weapon_size, "weapon", weapon)
    shape = parts.apply(shape, size, "head", head)
    seed = bytes([6 | MULTICOLOUR] * len(shape))
    colours = parts.colours_for(shape, c64_part_colours(icon_colours), seed)
    return icons.icon_pixels(icons.Icon(shape + colours), charset)


def dos_figure(game: pathlib.Path, size: str, body: int, head: int,
               icon_colours: bytes) -> list[list[list[int]]]:
    out = []
    for pose in (0, 1):
        bodies = ic.dos_options(game, "CBODY", size, pose)
        heads = ic.dos_options(game, "CHEAD", size, pose)
        out.append(dos_recoloured(ic._composite(bodies[body], heads[head]),
                                  icon_colours))
    return out


def sheet(game: pathlib.Path, disk: pathlib.Path, kind: str, size: str,
          icon_colours: bytes, path: pathlib.Path, scale: int = 5) -> None:
    from PIL import Image, ImageDraw

    parts = IconParts.load(str(disk))
    charset = icons.load_icon_charset(str(disk))
    table = WEAPONS if kind == "weapon" else HEADS
    alternatives = WEAPON_ALTERNATIVES if kind == "weapon" else HEAD_ALTERNATIVES
    rows = []
    for dos_index, c64_index in sorted(table.items()):
        body, head = (dos_index, 0) if kind == "weapon" else (0, dos_index)
        left = dos_figure(game, size, body, head, icon_colours)
        options = (c64_index,) + alternatives.get(dos_index, ())
        rights = []
        for option in options:
            weapon, c_head = ((option, HEADS[0]) if kind == "weapon"
                              else (WEAPONS[0], option))
            px = c64_figure(parts, charset, size, weapon, c_head, icon_colours)
            rights.append((option, [px[:24], px[24:48]]))
        rows.append((dos_index, left, rights))
    cell, pad, label = 24 * scale, 6, 12
    widest = max(len(r) for _, _, r in rows)
    width = pad + (1 + widest) * (2 * cell + 3 * pad)
    height = pad + len(rows) * (cell + pad + label)
    image = Image.new("RGB", (width, height), "#303030")
    draw = ImageDraw.Draw(image)
    for r, (dos_index, left, rights) in enumerate(rows):
        top = pad + r * (cell + pad + label)
        columns = [(f"DOS {size} {kind} {dos_index}", ic.EGA, left)]
        for i, (option, px) in enumerate(rights):
            tag = "proposed" if i == 0 else "alternative"
            columns.append((f"C64 {option} {tag}", tuple(icons.C64_PALETTE), px))
        for c, (text, palette, poses) in enumerate(columns):
            x = pad + c * (2 * cell + 3 * pad)
            draw.text((x, top), text, fill="#FFFF80" if c else "#FFFFFF")
            for p, pixels in enumerate(poses):
                x0 = x + p * (cell + pad)
                for y, line in enumerate(pixels[:24]):
                    for xx, value in enumerate(line[:24]):
                        draw.rectangle(
                            [x0 + xx * scale, top + label + y * scale,
                             x0 + xx * scale + scale - 1,
                             top + label + y * scale + scale - 1],
                            fill=palette[value & 0x0F])
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"{path}  {image.width}x{image.height}")


def print_tables() -> None:
    print("DOS body -> C64 weapon (alternatives in brackets)")
    for n, o in sorted(WEAPONS.items()):
        alt = WEAPON_ALTERNATIVES.get(n, ())
        print(f"  {n:2} -> {o:2}  {list(alt) if alt else ''}")
    print("DOS head -> C64 head")
    for n, o in sorted(HEADS.items()):
        alt = HEAD_ALTERNATIVES.get(n, ())
        print(f"  {n:2} -> {o:2}  {list(alt) if alt else ''}")
    print("EGA -> C64:", " ".join(f"{i}:{c}" for i, c in enumerate(EGA_TO_C64)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dos", help="the DOS game directory")
    ap.add_argument("--disk", help="POOL3.D64")
    ap.add_argument("--kind", default="weapon", choices=("weapon", "head"))
    ap.add_argument("--size", default="large", choices=("small", "large"))
    ap.add_argument("--colours", default=DEFAULT_COLOURS.hex(),
                    help="the record's six icon_colours bytes, as hex")
    ap.add_argument("--png", metavar="PATH", help="draw the table, under work/")
    args = ap.parse_args(argv)
    colours = bytes.fromhex(args.colours)
    if len(colours) != 6:
        raise SystemExit("--colours is six bytes: twelve hex digits")
    if args.png:
        sheet(ic.dos_game(args.dos), ic.c64_disk(args.disk), args.kind,
              args.size, colours, pathlib.Path(args.png))
    else:
        print_tables()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
