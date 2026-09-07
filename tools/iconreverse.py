#!/usr/bin/env python3
"""The proposed C64-to-DOS combat-figure table, drawn so it can be judged (#320).

`#320 (A C64 party converted to DOS arrives with no combat figure at all,
because the table only runs one way)` is the mirror of `#130 (A converted
DOS party arrives with six identical combat figures, not its own)`. A C64
record stores the eighteen screen codes an icon *is* rather than an index, so
converting one to DOS is two jobs: read the menu choices back out of the
cells, and say which DOS body and head each C64 option becomes.

The first is arithmetic and lives in `goldbox.iconparts.IconParts.recognise`.
The second is a judgement, and Donald ruled on 2026-09-07 how it gets made --
*"Draft it, you correct it"*: an agent proposes every row with its reasoning
and any close alternatives, and he edits the ones he disagrees with. This tool
holds nothing but the drawing and the accounting; the table itself is
`tools/iconreverse.yaml`, beside this file, which is the single source and is
edited by hand.

    tools/iconreverse.py                       the table, as text
    tools/iconreverse.py --coverage            how many rows are forced, and by what
    tools/iconreverse.py --census              every icon on the player's own disks,
                                               read back into menu choices
    tools/iconreverse.py --markdown work/issue320/proposal/proposal.md
    tools/iconreverse.py --png work/issue320/reverse-weapons.png

**`--markdown` is the form a person can only look at.** One row per C64
option: the C64 figure on the left, the DOS figure it is proposed to become
beside it, any alternatives after that, and the comment saying why. A gallery
of every DOS option follows each table, numbered, so a preferred alternative
can be named. To change a row, edit the YAML and run this again -- there is no
reading the document back, for the reason `tools/iconproposal.py` gives.

**The pictures are the game's own art.** They go under `work/` and are never
committed. The table of numbers is a measurement and is committed, which is
the line `.claude/rules/conversions.md` draws.
"""

from __future__ import annotations

import argparse
import collections
import glob
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import iconproposal as ip  # noqa: E402

from goldbox import games, icons  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.iconparts import IconParts, dos_icon_tables  # noqa: E402
from tools import gamedisks  # noqa: E402

#: `tools/iconreverse.yaml`, the single source. It stays in `tools/` for the
#: same reason `tools/iconproposal.yaml` does -- Donald edits it where he has
#: already been shown it. Nothing in `goldbox/` reads it yet; when the
#: conversion does, it needs `goldbox.assets.asset_path` and a `wish.spec`
#: row the way `#315 (A frozen Wish cannot convert a combat figure, because
#: the table it needs lives outside the package)` gave the forward one.
TABLE_PATH = pathlib.Path(__file__).with_name("iconreverse.yaml")

#: How many options each of the four C64 lists holds, so `--coverage` can say
#: a row is missing rather than silently not checking it. Read off the disk
#: when one is available; these are what `SPELLN64`'s `$B0DA` carries in all
#: three titles.
LIST_SIZES = {("large", "weapons"): 35, ("large", "heads"): 23,
              ("small", "weapons"): 28, ("small", "heads"): 14}

#: What DOS offers, which is the same 32 bodies and 14 heads in all three
#: titles -- the engine's own ICON menu wraps at 31 and 13 (#130).
DOS_SIZES = {"weapons": 32, "heads": 14}

#: The C64 icon table's offset inside a save payload, shared by Pool of
#: Radiance's `SAVEDGAME0`, Curse's `SAVEAZURE` and Silver Blades'
#: `SAVEDBASH` (`goldbox/c64_save.py`'s `Container.icon_table`).
ICON_TABLE_OFFSET = 0x2E0
SLOTS = 8

#: How many screen pixels one C64 pixel becomes in the document's figures.
#: Donald, 2026-09-07, reading the first draft: "The combat icons in
#: proposal.md are very small."  A figure is 24 pixels across, so this is a
#: 288-pixel drawing -- large enough to tell a mace from an axe without
#: opening the image.  `--scale` overrides it, and `sheet`'s single-page
#: layout keeps its own smaller default because it draws a whole list at once.
DOC_SCALE = 12

#: How wide each figure is *drawn* in the document, in screen pixels. A
#: markdown table shrinks a plain `![](...)` to whatever its column allows, so
#: a larger file alone changes nothing on screen -- Donald, 2026-09-07, on the
#: first attempt: "I can't tell any difference is the size of the icons."
#: Stating the width on an `<img>` tag is what actually makes them bigger, and
#: the table is seven columns wide, so this is the number to raise.
DOC_WIDTH = 300


def _img(name: str, width: int = DOC_WIDTH) -> str:
    """One figure, at a size the table cannot shrink."""
    return f'<img src="img/{name}" width="{width}">'


#: Which save file each title's disks carry, for `--census`.
SAVE_FILES = {"pool-of-radiance": b"SAVEDGAME0",
              "curse-of-the-azure-bonds": b"SAVEAZURE",
              "secret-of-the-silver-blades": b"SAVEDBASH"}


# -- the table ---------------------------------------------------------------

def load_tables(path: pathlib.Path = TABLE_PATH) -> dict:
    """The four option tables and the colour table, out of the YAML source.

    `{("large", "weapons"): {c64: (dos, alternatives)}, ...}` plus a
    `"colours"` entry mapping a C64 colour 0-7 to its `(low, high)` EGA pair.
    The shape mirrors `tools/iconproposal.py`'s `load_tables`, one level
    deeper because a C64 option number means a different drawing at each
    size.
    """
    data = yaml.safe_load(path.read_text())
    out: dict = {}
    for size in ("large", "small"):
        section = data if size == "large" else (data.get("small") or {})
        for kind in ("weapons", "heads"):
            rows = section.get(kind) or {}
            out[(size, kind)] = {
                int(k): (row["dos"], tuple(row.get("alt") or ()))
                for k, row in rows.items()}
    out["colours"] = {int(k): tuple(row["dos"])
                      for k, row in (data.get("colours") or {}).items()}
    return out


def print_tables(tables: dict) -> None:
    for size in ("large", "small"):
        for kind in ("weapons", "heads"):
            print(f"C64 {size} {kind[:-1]} -> DOS "
                  f"{'icon_body' if kind == 'weapons' else 'icon_head'} "
                  f"(alternatives in brackets)")
            for c64, (dos, alt) in sorted(tables[(size, kind)].items()):
                print(f"  {c64:2} -> {dos:2}  {list(alt) if alt else ''}")
    print("C64 colour -> DOS icon_colours pair (low, high)")
    for c64, pair in sorted(tables["colours"].items()):
        print(f"  {c64} -> {pair[0]:2}, {pair[1]:2}")


# -- the accounting ----------------------------------------------------------

def coverage(tables: dict) -> dict:
    """How each row of the reverse table is decided, per list.

    Three kinds, and the counts are what says how much of this is Donald's to
    judge:

    * **forced** -- exactly one DOS option becomes this C64 one in
      `tools/iconproposal.yaml`, so reversing it is the only answer that
      gives a player their own figure back on a round trip;
    * **choice** -- several DOS options become this C64 one, and which of
      them comes back is a pick among them. Any pick round-trips, so this is
      about the picture rather than about correctness;
    * **fresh** -- no DOS option becomes this C64 one at all, so the row is
      the nearest figure and nothing forces it.
    """
    out: dict = {}
    for size in ("large", "small"):
        forward = dos_icon_tables(size=size)
        for kind, table in (("weapons", forward.weapons),
                            ("heads", forward.heads)):
            count = LIST_SIZES[(size, kind)]
            preimages: dict[int, list[int]] = collections.defaultdict(list)
            for dos, c64 in table.items():
                if c64 < count:         # a row composed out of the large list
                    preimages[c64].append(dos)
            rows = tables[(size, kind)]
            kinds = {}
            for c64 in range(count):
                pre = sorted(preimages.get(c64, []))
                kinds[c64] = ("forced" if len(pre) == 1 else
                              "choice" if pre else "fresh")
            out[(size, kind)] = {
                "count": count,
                "missing": [c64 for c64 in range(count) if c64 not in rows],
                "preimages": {c64: sorted(preimages.get(c64, []))
                              for c64 in range(count)},
                "kinds": kinds,
                "disagrees": [c64 for c64, pre in preimages.items()
                              if c64 in rows and rows[c64][0] not in pre],
            }
    return out


def print_coverage(tables: dict) -> None:
    totals = collections.Counter()
    for (size, kind), row in coverage(tables).items():
        counts = collections.Counter(row["kinds"].values())
        totals.update(counts)
        print(f"C64 {size} {kind}: {row['count']} rows -- "
              f"{counts['forced']} forced, {counts['choice']} a choice among "
              f"the DOS options the forward table merged, {counts['fresh']} "
              f"with no DOS option of their own")
        if row["missing"]:
            print(f"    MISSING ROWS: {row['missing']}")
        if row["disagrees"]:
            print(f"    rows whose answer is not one of the DOS options that "
                  f"become them: {row['disagrees']}")
    print(f"all four lists: {sum(totals.values())} rows -- {totals['forced']} "
          f"forced, {totals['choice']} a choice, {totals['fresh']} fresh")


# -- reading the player's own icons back -------------------------------------

def census(parts: IconParts, folders: dict[str, pathlib.Path]) -> list[dict]:
    """Every icon on the disks in `folders`, read back into menu choices.

    One row per distinct shape, with how many slots carry it and where the
    first was found. The point is not the icons -- it is whether
    `IconParts.recognise` names a weapon and a head for every one of them,
    which is what the conversion has to do for a real save.
    """
    seen: dict[bytes, list[tuple[str, str, int]]] = collections.defaultdict(list)
    for title, folder in folders.items():
        name = SAVE_FILES.get(title)
        if name is None or folder is None:
            continue
        for pattern in ("*.d64", "*.D64"):
            for path in sorted(glob.glob(str(folder / pattern))):
                try:
                    payload = D64.open(path).read_file(name)[2:]
                except Exception:
                    continue
                for slot in range(SLOTS):
                    off = ICON_TABLE_OFFSET + slot * icons.ICON_SIZE
                    shape = bytes(payload[off:off + icons.CELLS])
                    if len(shape) < icons.CELLS or not any(shape):
                        continue
                    if set(shape) == {0x20}:
                        continue
                    seen[shape].append((title, pathlib.Path(path).name, slot))
    rows = []
    for shape, where in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        row = {"shape": shape.hex(), "slots": len(where), "where": where[0],
               "titles": sorted({t for t, _, _ in where})}
        try:
            choice = parts.recognise(shape)
        except ValueError as exc:
            row["error"] = str(exc)
        else:
            row["choice"] = choice
        rows.append(row)
    return rows


def print_census(rows: list[dict]) -> None:
    unread = ambiguous = 0
    for row in rows:
        title, disk, slot = row["where"]
        where = f"{disk}#{slot}"
        if "error" in row:
            unread += 1
            print(f"{row['shape']}  n={row['slots']:3d}  UNREAD  {where}")
            continue
        c = row["choice"]
        if c.alternatives:
            ambiguous += 1
        alt = (f"  head also {[f'{s} {o}' for s, o in c.alternatives]}"
               if c.alternatives else "")
        print(f"{row['shape']}  n={row['slots']:3d}  "
              f"{c.weapon_size} weapon {c.weapon:2d}, "
              f"{c.head_size} head {c.head:2d}"
              f"{'' if c.exact else '  (carries a cell from an earlier choice)'}"
              f"{alt}  {where}")
    total = sum(r["slots"] for r in rows)
    print(f"{total} icons, {len(rows)} distinct shapes: "
          f"{len(rows) - unread} read back into menu choices, {unread} not; "
          f"{ambiguous} name more than one head")


# -- drawing -----------------------------------------------------------------

def c64_row_figure(parts: IconParts, charset: bytes, size: str, kind: str,
                   option: int, icon_colours: bytes):
    """One C64 option on an otherwise default figure, both poses."""
    weapon, head = ((option, 1) if kind == "weapons" else (0, option))
    px = ip.c64_figure(parts, charset, size, weapon, head, icon_colours)
    return [px[:24], px[24:48]]


def dos_row_figure(game: pathlib.Path, size: str, kind: str, option: int,
                   icon_colours: bytes):
    """The DOS body or head a row proposes, both poses."""
    body, head = ((option, 0) if kind == "weapons" else (0, option))
    return ip.dos_figure(game, size, body, head, icon_colours)


def sheet(parts: IconParts, charset: bytes, game: pathlib.Path, tables: dict,
          size: str, kind: str, icon_colours: bytes, path: pathlib.Path,
          scale: int = 5) -> None:
    """One list as a single sheet: every C64 option beside its DOS answer."""
    from PIL import Image, ImageDraw

    rows = []
    for c64, (dos, alt) in sorted(tables[(size, kind)].items()):
        left = c64_row_figure(parts, charset, size, kind, c64, icon_colours)
        rights = [(d, dos_row_figure(game, size, kind, d, icon_colours))
                  for d in (dos, *alt)]
        rows.append((c64, left, rights))
    cell, pad, label = 24 * scale, 6, 12
    widest = max(len(r) for _, _, r in rows)
    width = pad + (1 + widest) * (2 * cell + 3 * pad)
    height = pad + len(rows) * (cell + pad + label)
    image = Image.new("RGB", (width, height), "#303030")
    draw = ImageDraw.Draw(image)
    for r, (c64, left, rights) in enumerate(rows):
        top = pad + r * (cell + pad + label)
        columns = [(f"C64 {size} {kind[:-1]} {c64}",
                    tuple(icons.C64_PALETTE), left)]
        for i, (dos, poses) in enumerate(rights):
            tag = "proposed" if i == 0 else "alternative"
            columns.append((f"DOS {dos} {tag}", ip.ic.EGA, poses))
        for c, (text, palette, poses) in enumerate(columns):
            x = pad + c * (2 * cell + 3 * pad)
            draw.text((x, top), text, fill="#FFFF80" if c else "#FFFFFF")
            for p, pixels in enumerate(poses):
                x0 = x + p * (cell + pad)
                for y, line in enumerate(pixels[:24]):
                    for xx, value in enumerate(line[:24]):
                        colour = palette[value & 0x0F]
                        draw.rectangle(
                            [x0 + xx * scale, top + label + y * scale,
                             x0 + xx * scale + scale - 1,
                             top + label + y * scale + scale - 1], fill=colour)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"{path}  {image.width}x{image.height}")


def markdown(parts: IconParts, charset: bytes, game: pathlib.Path,
             tables: dict, icon_colours: bytes, out: pathlib.Path,
             title: str = "pool-of-radiance",
             scale: int = DOC_SCALE,
             width: int = DOC_WIDTH) -> None:
    """The proposal as a document, generated fresh from the YAML (#320)."""
    comments = _comments(TABLE_PATH.read_text())
    img = out.parent / "img"
    display = games.by_key(title).title
    cover = coverage(tables)
    lines = [
        f"# The proposed combat-figure table for a {display} save leaving "
        f"the Commodore 64, for #320",
        "",
        "Each row is one figure a Commodore 64 player can pick, and the DOS",
        "figure it would become. **Edit `tools/iconreverse.yaml`** and run",
        f"`tools/iconreverse.py --markdown {out}` to redraw this document.",
        "The gallery at the end of each table is every option DOS offers.",
        "",
        "The Commodore 64 figure is drawn in the colours a converted record",
        "carries and the DOS one in the colours it converts to, so a row that",
        "looks wrong is wrong for the reason you can see.",
        "",
        "**Rows marked *forced* are not yours to choose.** Exactly one DOS",
        "figure becomes that Commodore 64 one in the table the other",
        "direction already uses, so reversing it is what returns a player",
        "their own figure when a save goes back. They are here to be read.",
        "*A choice* means several DOS figures become this one and any of them",
        "comes back correctly, so the pick is about the picture. *Judgement*",
        "means DOS has no figure for this one at all.",
        "",
        "This file and its images are the game's own art. They live under",
        "`work/` and must never be committed.",
        "",
    ]
    for size in ("large", "small"):
        lines += [f"## The {size} lists", ""]
        if size == "small":
            lines += [
                "A Commodore 64 dwarf, gnome or halfling draws from these,",
                "and an option number here is a different picture from the",
                "same number above.",
                "",
            ]
        for kind in ("weapons", "heads"):
            row = cover[(size, kind)]
            counts = collections.Counter(row["kinds"].values())
            lines += [
                f"### C64 {size} {kind} to DOS "
                f"{'icon_body' if kind == 'weapons' else 'icon_head'}",
                "",
                f"{row['count']} rows: {counts['forced']} forced, "
                f"{counts['choice']} a choice, {counts['fresh']} judgement.",
                "",
                "| C64 | | Proposed | | How | Alternatives | Why |",
                "|---:|---|---:|---|---|---|---|",
            ]
            for c64, (dos, alt) in sorted(tables[(size, kind)].items()):
                left = f"c64-{size}-{kind}-{c64:02d}@{scale}.png"
                _save(c64_row_figure(parts, charset, size, kind, c64,
                                     icon_colours),
                      tuple(icons.C64_PALETTE), img / left, scale)
                cells = [str(c64), _img(left, width), str(dos),
                         _dos_cell(game, size, kind, dos, icon_colours, img,
                                   scale, width),
                         row["kinds"][c64],
                         " ".join(
                             f"{d} " + _dos_cell(game, size, kind, d,
                                                 icon_colours, img, scale,
                                                 width)
                             for d in alt),
                         comments.get((size, kind, c64), "")]
                lines.append("| " + " | ".join(cells) + " |")
            lines += ["", f"#### Every DOS {kind[:-1]}, to swap from", "",
                      "| | | |", "|---|---|---|"]
            gallery = []
            for option in range(DOS_SIZES[kind]):
                gallery.append(f"**{option}**<br>" + _dos_cell(
                    game, size, kind, option, icon_colours, img, scale, width))
                if len(gallery) == 3:
                    lines.append("| " + " | ".join(gallery) + " |")
                    gallery = []
            if gallery:
                lines.append("| " + " | ".join(
                    gallery + [""] * (3 - len(gallery))) + " |")
            lines.append("")
    lines += ["## Colours", "",
              "Nothing here is a judgement; the note in the YAML says why.",
              "", "| C64 | DOS pair |", "|---|---|"]
    for c64, pair in sorted(tables["colours"].items()):
        lines.append(f"| {c64} {icons.C64_COLOURS[c64]} | "
                     f"{pair[0]}, {pair[1]} |")
    lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"{out}  {len(lines)} lines, images in {img}")


def _save(poses, palette, path: pathlib.Path, scale: int = DOC_SCALE) -> None:
    ip.save_figure(poses, palette, path, scale)


def _dos_cell(game: pathlib.Path, size: str, kind: str, option: int,
              icon_colours: bytes, img: pathlib.Path,
              scale: int = DOC_SCALE, width: int = DOC_WIDTH) -> str:
    # The scale is in the file name so a document redrawn bigger does not
    # reuse the smaller images the last run left in the same directory.
    name = f"dos-{size}-{kind}-{option:02d}@{scale}.png"
    if not (img / name).exists():
        _save(dos_row_figure(game, size, kind, option, icon_colours),
              ip.ic.EGA, img / name, scale)
    return _img(name, width)


def _comments(text: str) -> dict[tuple[str, str, int], str]:
    """The trailing comment on each row of the YAML, as one line of prose.

    The comment is the whole argument for a row, so a document that dropped
    it would be a table of numbers with the reasoning left in a file Donald
    is not reading. Parsed out of the source rather than stored twice.
    """
    out: dict[tuple[str, str, int], str] = {}
    size, kind, current, indent = "large", None, None, 0
    for line in text.splitlines():
        stripped = line.strip()
        here = len(line) - len(line.lstrip())
        if stripped == "small:":
            size, current = "small", None
            continue
        if stripped in ("weapons:", "heads:"):
            kind, current = stripped[:-1], None
            continue
        if stripped == "colours:":
            kind, current = None, None
            continue
        if kind is None:
            continue
        if stripped.startswith("#"):
            #: A continuation of the row above only when it is indented
            #: past the row's own key.  A comment at the key's indent or
            #: less introduces the *next* section, and appending it to the
            #: last row put a paragraph about the small heads at the end of
            #: small weapon 27's reasoning.
            if current is not None and here > indent:
                out[current] = (out[current] + " "
                                + stripped.lstrip("# ")).strip()
            continue
        if ":" in stripped and stripped.split(":", 1)[0].strip().isdigit():
            number = int(stripped.split(":", 1)[0])
            current, indent = (size, kind, number), here
            body = stripped.split("#", 1)
            out[current] = body[1].strip() if len(body) > 1 else ""
    return out


# -- where things are --------------------------------------------------------

def c64_disk(title: str, given: str | None) -> pathlib.Path | None:
    """The side of `title`'s own C64 disk set carrying the icon art."""
    return ip.title_c64_disk(title, given)


def save_folders() -> dict[str, pathlib.Path | None]:
    """Each title's own C64 disk folder, for `--census`."""
    return {title: gamedisks.find(title) for title in SAVE_FILES}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dos", help="the DOS game directory")
    ap.add_argument("--disk", help="the C64 side carrying SPELLE64, SPELLN64 "
                                   "and CHARPIC00; found from the title's own "
                                   "disks when not given")
    ap.add_argument("--title", default="pool-of-radiance",
                    choices=ip.DOS_TITLES, help="whose art to draw")
    ap.add_argument("--archives", help="the unpacked Forgotten Realms "
                                       "archives, for a --title other than "
                                       "pool-of-radiance")
    ap.add_argument("--size", default="large", choices=("small", "large"))
    ap.add_argument("--kind", default="weapons", choices=("weapons", "heads"))
    ap.add_argument("--colours", default=ip.DEFAULT_COLOURS.hex(),
                    help="a record's six icon_colours bytes, as hex")
    ap.add_argument("--scale", type=int, default=None, metavar="N",
                    help=f"screen pixels per C64 pixel; default {DOC_SCALE} "
                         "for --markdown and 5 for --png")
    ap.add_argument("--width", type=int, default=DOC_WIDTH, metavar="N",
                    help="how wide each figure is drawn in --markdown, "
                         "in screen pixels; default 300")
    ap.add_argument("--coverage", action="store_true",
                    help="how many rows are forced by the forward table")
    ap.add_argument("--census", action="store_true",
                    help="read every icon on the player's own disks back "
                         "into menu choices")
    ap.add_argument("--png", metavar="PATH", help="draw one list, under work/")
    ap.add_argument("--markdown", metavar="PATH",
                    help="write the proposal as a document, generated fresh "
                         "from tools/iconreverse.yaml")
    args = ap.parse_args(argv)
    colours = bytes.fromhex(args.colours)
    if len(colours) != 6:
        raise SystemExit("--colours is six bytes: twelve hex digits")
    tables = load_tables()

    if args.coverage:
        print_coverage(tables)
        return 0
    if args.census:
        disk = c64_disk(args.title, args.disk)
        if disk is None:
            raise SystemExit(f"no {games.by_key(args.title).title} C64 disk "
                             f"carrying the icon files; pass --disk")
        print_census(census(IconParts.load(str(disk)), save_folders()))
        return 0
    if args.png or args.markdown:
        disk = c64_disk(args.title, args.disk)
        if disk is None:
            raise SystemExit(f"no {games.by_key(args.title).title} C64 disk "
                             f"carrying the icon files; pass --disk")
        parts = IconParts.load(str(disk))
        charset = icons.load_icon_charset(str(disk))
        game = ip.title_dos_game(args.title, args.dos, args.archives)
        if args.png:
            sheet(parts, charset, game, tables, args.size, args.kind, colours,
                  pathlib.Path(args.png),
                  **({"scale": args.scale} if args.scale else {}))
        else:
            markdown(parts, charset, game, tables, colours,
                     pathlib.Path(args.markdown), title=args.title,
                     scale=args.scale or DOC_SCALE, width=args.width)
        return 0
    print_tables(tables)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
