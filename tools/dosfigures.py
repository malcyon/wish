#!/usr/bin/env python3
"""Convert a DOS save to a C64 disk where each character keeps his own figure.

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)`: the shipped conversion writes one composed default into all six
slots, so a DOS party of an archer, a robed mage and four fighters arrives on
the combat floor as six identical unarmed men.  This builds the same disk
`tools/dosdisk.py` builds and then gives every character the figure his own
DOS record names, through `goldbox.iconparts.IconParts.dos_icon`.

    tools/dosfigures.py --folder ~/wish-specimens/... --slot C \\
        --out work/issue130/FIGURES.D64 --json work/issue130/figures.json

**This is the mechanism, not the button.**  `goldbox/dos.py`'s `convert_save`
takes one 36-byte `icon` and hands the same bytes to every character, so the
per-character composition cannot yet happen inside it; this tool composes the
six icons and writes them over the icon table after `dos.new_save` has run.
The bytes it produces are the bytes the one-argument change to `convert_save`
would produce, and the point of the tool is that they can be booted and
looked at before that change lands.  When it has landed, this becomes a
reporting tool and the two writes below come out.

The DOS folder is `--folder`, or found the way `tools/dosdisk.py` finds it.
The game disks come from `$POR_DISKS`, then `automap.paths.find_disks()`, and
are read and never written; the output goes wherever `--out` says, which
should be under `work/`.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

from automap.paths import find_disks  # noqa: E402
from goldbox import dos  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.iconparts import IconParts, dos_icon_tables, dos_size  # noqa: E402
from goldbox.icons import ICON_SIZE, ICON_TABLE_BASE  # noqa: E402
from goldbox.portraits import PortraitError, tables_from_disks  # noqa: E402
from goldbox.savegame import SAVE0_LOAD_ADDRESS  # noqa: E402

#: Where the player keeps the C64 game disks.  Read only.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")


def parts_from(disks: pathlib.Path) -> IconParts:
    """The four icon option tables, off whichever side carries them."""
    for path in sorted(disks.glob("*.[dD]64")):
        try:
            return IconParts.load(str(path))
        except Exception:
            continue
    raise SystemExit(f"no SPELLE64/SPELLN64 on any disk in {disks}")


def charset_from(disks: pathlib.Path) -> bytes:
    """`CHARPIC00`, the combat character set, off whichever side carries it."""
    from goldbox import icons

    for path in sorted(disks.glob("*.[dD]64")):
        try:
            return icons.load_icon_charset(str(path))
        except Exception:
            continue
    raise SystemExit(f"no CHARPIC00 on any disk in {disks}")


def figures(folder: pathlib.Path, slot: str, parts: IconParts,
            ) -> list[dict]:
    """One row a character: what DOS holds, and what it composes to.

    The slot is `dos.marching_slot`'s, which is the conversion's own answer
    for where a DOS marching position lands on the C64.
    """
    tables = dos_icon_tables()
    party = dos.read_party(folder, slot)
    rows = []
    for index, char in enumerate(party):
        head = char.get("icon_head")
        body = char.get("icon_body")
        size = dos_size(char.get("size"))
        colours = bytes(char.get("icon_colours"))
        icon = parts.dos_icon(head, body, size, colours, tables)
        rows.append({
            "name": char.name,
            "marching": index,
            "slot": dos.marching_slot(index, len(party)),
            "dos_head": head,
            "dos_body": body,
            "dos_size": size,
            "dos_colours": colours.hex(),
            "c64_weapon": tables.weapons[body],
            "c64_head": tables.heads[head],
            "codes": icon[:18].hex(),
            "colours": icon[18:].hex(),
        })
    return rows


def build(folder: pathlib.Path, slot: str, disks: pathlib.Path,
          out: pathlib.Path) -> list[dict]:
    """Write `out` and return one row a character.  Nothing else is touched."""
    parts = parts_from(disks)
    rows = figures(folder, slot, parts)
    try:
        portraits = tables_from_disks(disks)
    except PortraitError:
        portraits = None
    save0, save1, _report = dos.new_save(
        folder, slot, parts.default_icon(),
        dosdisk_animate(disks), portraits=portraits)
    save0 = bytearray(save0)
    for row in rows:
        at = (ICON_TABLE_BASE - SAVE0_LOAD_ADDRESS + row["slot"] * ICON_SIZE)
        save0[at:at + ICON_SIZE] = (bytes.fromhex(row["codes"])
                                    + bytes.fromhex(row["colours"]))
    disk: D64 = dos.save_disk(bytes(save0), bytes(save1))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(disk.data)
    return rows


def dosdisk_animate(disks: pathlib.Path) -> bytes:
    """`ANIMATE00`, the way `tools/dosdisk.py` fetches it."""
    import dosdisk

    return dosdisk.game_files(disks)[1]


def png(rows: list[dict], disks: pathlib.Path,
        path: pathlib.Path, scale: int = 5) -> None:
    """Each character's DOS figure beside the figure he converts to.

    Both poses of both, the DOS side in the record's own EGA colours and the
    C64 side in the colours the conversion gave it, so a row can be judged by
    looking.  The image is the game's art and goes under `work/`.
    """
    import iconcorrespond as ic
    import iconproposal as ip
    from PIL import Image, ImageDraw

    from goldbox import icons

    game = ic.dos_game(None)
    charset = charset_from(disks)
    cell, pad, label = 24 * scale, 8, 12
    image = Image.new("RGB", (pad + 4 * (cell + pad) + 3 * pad,
                              pad + len(rows) * (cell + pad + label)),
                      "#303030")
    draw = ImageDraw.Draw(image)
    for r, row in enumerate(rows):
        top = pad + r * (cell + pad + label)
        colours = bytes.fromhex(row["dos_colours"])
        left = ip.dos_figure(game, row["dos_size"], row["dos_body"],
                             row["dos_head"], colours)
        icon = icons.Icon(bytes.fromhex(row["codes"])
                          + bytes.fromhex(row["colours"]))
        px = icons.icon_pixels(icon, charset)
        draw.text((pad, top), f"{row['name']}  DOS body {row['dos_body']} "
                              f"head {row['dos_head']} {row['dos_size']}",
                  fill="#FFFFFF")
        draw.text((pad + 2 * (cell + pad) + 2 * pad, top),
                  f"C64 weapon {row['c64_weapon']} head {row['c64_head']}",
                  fill="#FFFF80")
        panels = [(ic.EGA, left[0]), (ic.EGA, left[1]),
                  (tuple(icons.C64_PALETTE), px[:24]),
                  (tuple(icons.C64_PALETTE), px[24:48])]
        for c, (palette, pixels) in enumerate(panels):
            x0 = pad + c * (cell + pad) + (2 * pad if c >= 2 else 0)
            for y, line in enumerate(pixels[:24]):
                for x, value in enumerate(line[:24]):
                    draw.rectangle([x0 + x * scale, top + label + y * scale,
                                    x0 + x * scale + scale - 1,
                                    top + label + y * scale + scale - 1],
                                   fill=palette[value & 0x0F])
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"{path}  {image.width}x{image.height}")


def mixed_png(disks: pathlib.Path, path: pathlib.Path, scale: int = 6) -> None:
    """The nine rows where a small character has to wear a large option.

    The C64 offers a small character 28 weapons and 14 heads against a large
    one's 35 and 23, and Donald's table lands past the small lists in six
    weapon rows and three head rows.  Those are composed from the large list,
    which is a mixed icon and one the game's own menus reach.  Whether it
    *looks* right is a judgement and needs a picture, so here is one: each
    large-only option on a small figure, with four small options above it to
    compare against.
    """
    from PIL import Image, ImageDraw

    from goldbox import icons
    from goldbox.iconparts import (
        DEFAULT_BACKGROUND,
        MULTICOLOUR,
        SPACE,
        dos_part_colours,
    )

    parts = parts_from(disks)
    charset = charset_from(disks)
    tables = dos_icon_tables()
    per_class = dos_part_colours(bytes.fromhex("91a2b3c4e6f7"), tables)
    small_heads = parts.count("small", "head")
    small_weapons = parts.count("small", "weapon")
    rows = []
    for kind, option in ([("head", h) for h in (0, 3, 5, 13)]
                         + sorted({("head", tables.heads[h])
                                   for h in tables.heads
                                   if tables.heads[h] >= small_heads})
                         + sorted({("weapon", tables.weapons[b])
                                   for b in tables.weapons
                                   if tables.weapons[b] >= small_weapons})):
        big = (option >= (small_heads if kind == "head" else small_weapons))
        shape = bytes([SPACE] * 18)
        shape = parts.apply(shape, "large" if big and kind == "weapon"
                            else "small", "weapon",
                            option if kind == "weapon" else 8)
        shape = parts.apply(shape, "large" if big and kind == "head"
                            else "small", "head",
                            option if kind == "head" else 0)
        seed = bytes([DEFAULT_BACKGROUND | MULTICOLOUR] * 18)
        icon = icons.Icon(shape + parts.colours_for(shape, per_class, seed))
        rows.append((f"small figure, {'large-only ' if big else 'small '}"
                     f"{kind} {option}", icons.icon_pixels(icon, charset)))
    cell, pad, label = 24 * scale, 8, 12
    image = Image.new("RGB", (pad + 2 * (cell + pad),
                              pad + len(rows) * (cell + pad + label)),
                      "#303030")
    draw = ImageDraw.Draw(image)
    palette = tuple(icons.C64_PALETTE)
    for r, (text, px) in enumerate(rows):
        top = pad + r * (cell + pad + label)
        draw.text((pad, top), text, fill="#FFFFFF")
        for c, pixels in enumerate((px[:24], px[24:48])):
            x0 = pad + c * (cell + pad)
            for y, line in enumerate(pixels[:24]):
                for x, value in enumerate(line[:24]):
                    draw.rectangle([x0 + x * scale, top + label + y * scale,
                                    x0 + x * scale + scale - 1,
                                    top + label + y * scale + scale - 1],
                                   fill=palette[value & 0x0F])
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"{path}  {image.width}x{image.height}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--folder", default=None,
                   help="the DOS save directory; read, never written")
    p.add_argument("--slot", default=None, help="the DOS save slot letter")
    p.add_argument("--out", default=None, help="the .d64 to write, under work/")
    p.add_argument("--mixed-png", default=None,
                   help="draw the nine rows a small character wears large, "
                        "and write nothing else")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's game disks are; read, never written")
    p.add_argument("--json", default=None, help="where the per-character log goes")
    p.add_argument("--png", default=None,
                   help="draw each DOS figure beside the one it converts to")
    args = p.parse_args(argv)

    if args.mixed_png:
        mixed_png(pathlib.Path(args.disks), pathlib.Path(args.mixed_png))
        return 0
    if not args.slot or not args.out:
        p.error("--slot and --out are needed to convert a save")

    folder = pathlib.Path(args.folder) if args.folder else _dos_folder()
    rows = build(folder, args.slot, pathlib.Path(args.disks),
                 pathlib.Path(args.out))
    for row in rows:
        print(f"slot {row['slot']} {row['name']:<12} "
              f"DOS body {row['dos_body']:>2} head {row['dos_head']:>2} "
              f"{row['dos_size']:<5} {row['dos_colours']}  ->  "
              f"C64 weapon {row['c64_weapon']:>2} head {row['c64_head']:>2}  "
              f"{row['codes']}")
    distinct = len({row["codes"] for row in rows})
    print(f"{distinct} distinct figures among {len(rows)} characters")
    if args.json:
        path = pathlib.Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2))
    if args.png:
        png(rows, pathlib.Path(args.disks), pathlib.Path(args.png))
    return 0


def _dos_folder() -> pathlib.Path:
    import dosdisk

    return dosdisk.dos_folder()


if __name__ == "__main__":
    raise SystemExit(main())
