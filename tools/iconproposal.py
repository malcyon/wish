#!/usr/bin/env python3
"""The proposed DOS-to-C64 combat-figure table, drawn so it can be judged (#130).

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)` ends in a judgement: which of the C64's weapon and head options
each of the DOS game's 32 bodies and 14 heads becomes.  The two ports draw
the same *kinds* of figure -- an archer, a flail, a sword and shield, a
robed caster -- in different orders and from different art, so no
measurement picks the rows, and the ticket says the choice is Donald's.

This tool holds the **proposal** -- three tables read from
`tools/iconproposal.yaml`, which is the single source Donald edits by hand --
and draws every row as the two games would draw it: the DOS figure in its own
record colours on the left, the proposed C64 figure on the right in the
colours the same record converts to.  Nothing here converts a save; when the
tables are approved they move into `goldbox/`, and until then they are a
picture on the issue.

    tools/iconproposal.py --markdown work/issue130/proposal/proposal.md
    tools/iconproposal.py --png work/issue130/proposal-weapons.png
    tools/iconproposal.py --kind head --png work/issue130/proposal-heads.png
    tools/iconproposal.py --colours 91a2b3c4e6f7      # a record's own six bytes
    tools/iconproposal.py                             # the tables, as text

**`--markdown` is the form a person can only look at, generated fresh each
time from the YAML.** A document with one image per figure lets a row be
judged, because judging needs the figure you might move *to* beside the one
you are judging *from*, and a gallery of every option at the end. To change a
row, edit `tools/iconproposal.yaml` and regenerate the document; there used to
be a `--from-markdown` that read the document back, and it is gone, because a
YAML file a person edits directly cannot be overwritten by regenerating the
document the way the markdown round trip could.

The DOS side is read the way `tools/iconcorrespond.py` reads it, off the
player's own `CHEAD.DAX`/`CBODY.DAX`; the C64 side is composed by
`goldbox.iconparts` from `POOL3.D64`.  The PNG is the game's art and goes
under `work/`, never into the repository.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import iconcorrespond as ic  # noqa: E402

from goldbox import icons  # noqa: E402
from goldbox.iconparts import (  # noqa: E402
    MULTICOLOUR,
    IconParts,
    dos_icon_tables,
    dos_part_colours,
)

# -- the proposal -------------------------------------------------------------
#
# The three tables -- which C64 weapon each DOS body becomes, which C64 head
# each DOS head becomes, and EGA colour to C64 colour -- are Donald's
# judgement and live in `tools/iconproposal.yaml`, beside this file, so he can
# edit them without touching Python. Every row there is a look at
# `work/issue130/big-*.png`, not a measurement.

#: `tools/iconproposal.yaml`, the single source for the three tables below.
TABLE_PATH = pathlib.Path(__file__).with_name("iconproposal.yaml")

Table = dict[int, int]
Alternatives = dict[int, tuple[int, ...]]


def load_tables(path: pathlib.Path = TABLE_PATH,
                ) -> tuple[Table, Alternatives, Table, Alternatives,
                          tuple[int, ...]]:
    """The weapon, head and colour tables, read out of the YAML source.

    Returns `(weapons, weapon_alternatives, heads, head_alternatives,
    ega_to_c64)`, the same shapes the tool used to hold as Python literals.
    """
    data = yaml.safe_load(path.read_text())

    def _table(section: str) -> tuple[Table, Alternatives]:
        table, alternatives = {}, {}
        for dos_index, row in data[section].items():
            table[int(dos_index)] = row["c64"]
            if row.get("alt"):
                alternatives[int(dos_index)] = tuple(row["alt"])
        return table, alternatives

    weapons, weapon_alternatives = _table("weapons")
    heads, head_alternatives = _table("heads")
    ega_to_c64 = tuple(data["colours"][i]["c64"]
                      for i in sorted(data["colours"]))
    return weapons, weapon_alternatives, heads, head_alternatives, ega_to_c64


(WEAPONS, WEAPON_ALTERNATIVES, HEADS, HEAD_ALTERNATIVES,
 EGA_TO_C64) = load_tables()

#: The shipped default set, `91 A2 B3 C4 E6 F7`.
DEFAULT_COLOURS = bytes.fromhex("91a2b3c4e6f7")

#: How the same three tables reach the conversion itself.  Drawn here and
#: applied there, out of the one YAML file, so a sheet is a picture of what a
#: converted character would actually get rather than of a second copy of the
#: rules (#130).
TABLES = dos_icon_tables()


def c64_part_colours(icon_colours: bytes) -> dict[int, int]:
    """The seven C64 part colours a DOS record's six colour pairs become."""
    return dos_part_colours(icon_colours, TABLES)


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
    """Both poses of the proposed C64 figure in the converted colours.

    A weapon or head numbered past the requested size's own list is drawn
    from the large list instead, the way `IconParts.dos_icon` composes a
    real conversion's mixed icon (#130) -- `parts.size_for` picks the size
    for each part on its own, since a row can need it for the weapon, the
    head, or neither (#325).
    """
    blank = bytes([0x20] * 18)
    shape = parts.apply(blank, parts.size_for(size, "weapon", weapon),
                        "weapon", weapon)
    shape = parts.apply(shape, parts.size_for(size, "head", head),
                        "head", head)
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
            mixed = parts.size_for(size, kind, option) != size
            rights.append((option, mixed, [px[:24], px[24:48]]))
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
        for i, (option, mixed, px) in enumerate(rights):
            tag = "proposed" if i == 0 else "alternative"
            note = ", large list only" if mixed else ""
            columns.append((f"C64 {option} {tag}{note}",
                            tuple(icons.C64_PALETTE), px))
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


def save_figure(poses, palette, path: pathlib.Path, scale: int = 4) -> None:
    """One figure, both poses side by side, as its own small PNG."""
    from PIL import Image

    cell, gap = 24 * scale, 2 * scale
    image = Image.new("RGB", (2 * cell + gap, cell), "#303030")
    pixels = image.load()
    for p, pose in enumerate(poses):
        x0 = p * (cell + gap)
        for y, line in enumerate(pose[:24]):
            for x, value in enumerate(line[:24]):
                colour = palette[value & 0x0F]
                if isinstance(colour, str):
                    colour = tuple(int(colour[i:i + 2], 16)
                                   for i in (1, 3, 5))
                for dy in range(scale):
                    for dx in range(scale):
                        pixels[x0 + x * scale + dx, y * scale + dy] = colour
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def markdown(game: pathlib.Path, disk: pathlib.Path, size: str,
             icon_colours: bytes, out: pathlib.Path) -> None:
    """The proposal as a document, generated fresh from the YAML (#130).

    One PNG per figure rather than one sheet per table, because judging a
    row needs the C64 figure it is proposed as, beside the DOS figure it is
    proposed *for*, as its own image. The gallery at the end is every option
    the C64 offers, numbered, so a preferred alternative can be named.

    The loop is: edit `tools/iconproposal.yaml`, and run this again -- there
    is no reading a document back, because the YAML is the only place the
    numbers live.
    """
    parts = IconParts.load(str(disk))
    charset = icons.load_icon_charset(str(disk))
    img = out.parent / "img"
    lines = [
        "# The proposed combat-figure table, for #130",
        "",
        "Each row is one DOS figure and the C64 figure it would become.",
        "**Edit `tools/iconproposal.yaml`** and run",
        f"`tools/iconproposal.py --markdown {out}` to redraw this document.",
        "The gallery at the end is every option the C64 offers.",
        "",
        "The DOS figure is drawn in its record's own colours and the C64 one",
        "in the colours that record converts to, so a row that looks wrong is",
        "wrong for the reason you can see.",
        "",
        "This file and its images are the game's own art. They live under",
        "`work/` and must never be committed.",
        "",
    ]
    for kind, table, alternatives in (
            ("weapon", WEAPONS, WEAPON_ALTERNATIVES),
            ("head", HEADS, HEAD_ALTERNATIVES)):
        lines += [f"## DOS {kind} to C64 {kind}", "",
                  "| DOS | | Proposed | | Alternatives |",
                  "|---:|---|---:|---|---|"]
        for dos_index, c64_index in sorted(table.items()):
            body, head = ((dos_index, 0) if kind == "weapon"
                          else (0, dos_index))
            name = f"dos-{kind}-{size}-{dos_index:02d}.png"
            save_figure(dos_figure(game, size, body, head, icon_colours),
                        ic.EGA, img / name)
            alts = []
            for option in alternatives.get(dos_index, ()):
                alts.append(f"{option} ![]({'img/' + _c64_png(parts, charset, size, kind, option, icon_colours, img)})")
            lines.append(
                f"| {dos_index} | ![](img/{name}) | {c64_index} | "
                f"![](img/{_c64_png(parts, charset, size, kind, c64_index, icon_colours, img)}) | "
                f"{' '.join(alts)} |")
        lines.append("")
        count = parts.count(size, kind)
        lines += [f"### Every C64 {kind}, to swap from", "",
                  "| | | | | | |", "|---|---|---|---|---|---|"]
        row = []
        for option in range(count):
            png = _c64_png(parts, charset, size, kind, option, icon_colours,
                           img)
            row.append(f"**{option}**<br>![](img/{png})")
            if len(row) == 6:
                lines.append("| " + " | ".join(row) + " |")
                row = []
        if row:
            lines.append("| " + " | ".join(row + [""] * (6 - len(row))) + " |")
        lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"{out}  {len(lines)} lines, images in {img}")


def _c64_png(parts, charset, size: str, kind: str, option: int,
             icon_colours: bytes, img: pathlib.Path) -> str:
    """Draw one C64 option if it is not drawn already, and name its file."""
    name = f"c64-{kind}-{size}-{option:02d}.png"
    if not (img / name).exists():
        weapon, head = ((option, HEADS[0]) if kind == "weapon"
                        else (WEAPONS[0], option))
        px = c64_figure(parts, charset, size, weapon, head, icon_colours)
        save_figure([px[:24], px[24:48]], tuple(icons.C64_PALETTE), img / name)
    return name


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
    ap.add_argument("--markdown", metavar="PATH",
                    help="write the proposal as a document, generated fresh "
                         "from tools/iconproposal.yaml, with one image per "
                         "figure")
    args = ap.parse_args(argv)
    colours = bytes.fromhex(args.colours)
    if len(colours) != 6:
        raise SystemExit("--colours is six bytes: twelve hex digits")
    if args.markdown:
        markdown(ic.dos_game(args.dos), ic.c64_disk(args.disk), args.size,
                 colours, pathlib.Path(args.markdown))
    elif args.png:
        sheet(ic.dos_game(args.dos), ic.c64_disk(args.disk), args.kind,
              args.size, colours, pathlib.Path(args.png))
    else:
        print_tables()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
