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
    tools/iconproposal.py --title secret-of-the-silver-blades --markdown work/issue330/silver-blades.md
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

**`--title` picks whose own DOS art `--markdown` and `--png` draw** --
`pool-of-radiance`, `curse-of-the-azure-bonds` or
`secret-of-the-silver-blades`, the three titles `#330 (A converted Curse or
Silver Blades figure is composed through Pool of Radiance's icon table,
which nobody has checked transfers)` measured. A title other than Pool of
Radiance's document is checked against Pool of Radiance's own art, block by
block, and every row says plainly whether this title draws the same figure
or its own; `#335 (Two combat-figure rows describe Pool of Radiance's art,
and Silver Blades draws those two options differently)` is where Secret of
the Silver Blades' two redrawn rows get their C64 answer.

The DOS side is read the way `tools/iconcorrespond.py` reads it, off the
requested title's own `CHEAD.DAX`/`CBODY.DAX`; the C64 side is composed by
`goldbox.iconparts` from `POOL3.D64`, whose `SPELLE64`/`SPELLN64` option
tables are the identical bytes in all three titles, so one disk draws it for
any of them (#330). The PNG is the game's art and goes under `work/`, never
into the repository.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import dosicontitles as dit  # noqa: E402
import iconcorrespond as ic  # noqa: E402

from goldbox import games, icons  # noqa: E402
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

#: The three DOS titles whose combat art `#330 (A converted Curse or Silver
#: Blades figure is composed through Pool of Radiance's icon table, which
#: nobody has checked transfers)` measured, in the order a document is
#: usually read.  Pools of Darkness is not here: its head blocks are a
#: different size, it has no pose-2 head blocks, and it never had a
#: Commodore 64 release, so there is nothing to convert its art to.
DOS_TITLES = ("pool-of-radiance", "curse-of-the-azure-bonds",
             "secret-of-the-silver-blades")


def load_overrides(path: pathlib.Path = TABLE_PATH,
                   ) -> dict[str, dict[str, Table]]:
    """The `overrides:` section: `{title: {"weapons": {...}, "heads": {...}}}`.

    Empty for a title with no section of its own -- every title today, since
    `#335 (Two combat-figure rows describe Pool of Radiance's art, and Silver
    Blades draws those two options differently)` has not been settled.  This
    is `--markdown`'s own reading of the section, for saying in a title's
    document whether a row is still the base table's; `goldbox.iconparts.
    dos_icon_tables` is the reader the conversion itself uses.
    """
    data = yaml.safe_load(path.read_text())
    out: dict[str, dict[str, Table]] = {}
    for title, sections in (data.get("overrides") or {}).items():
        out[title] = {
            kind: {int(k): row["c64"] for k, row in sections.get(kind, {}).items()}
            for kind in ("weapons", "heads")
        }
    return out


def tables_for_title(title: str, path: pathlib.Path = TABLE_PATH,
                     ) -> tuple[Table, Table]:
    """This title's own weapon and head tables, with its override applied.

    The base tables plus whatever `load_overrides` names for `title` -- the
    same merge `goldbox.iconparts.dos_icon_tables` makes for the conversion,
    so a title's document shows the C64 option a save of that title would
    actually become. Takes `path` itself, rather than reading the
    module-level `WEAPONS`/`HEADS`, so it can be pointed at a table other
    than `tools/iconproposal.yaml` in a test.
    """
    weapons, _, heads, _, _ = load_tables(path)
    override = load_overrides(path).get(title, {})
    weapons = dict(weapons)
    weapons.update(override.get("weapons", {}))
    heads = dict(heads)
    heads.update(override.get("heads", {}))
    return weapons, heads


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


def redrawn_sizes(game: pathlib.Path, reference: pathlib.Path, kind: str,
                  dos_index: int) -> list[str]:
    """Which sizes this title draws one row's figure differently from Pool of
    Radiance's own art (#330, #335).

    Compares the DOS part-value pixels, both poses -- the way
    `tools/dosicontitles.py` compares whole blocks -- rather than a
    recoloured picture, so a difference is never hidden by a coincidence of
    which colours a record happens to carry.  Empty whenever `game` and
    `reference` are the same folder, which is Pool of Radiance's own
    document: there is nothing for it to differ from.
    """
    if game == reference:
        return []
    body, head = (dos_index, 0) if kind == "weapon" else (0, dos_index)
    out = []
    for size in ("small", "large"):
        mine = [ic._composite(ic.dos_options(game, "CBODY", size, pose)[body],
                              ic.dos_options(game, "CHEAD", size, pose)[head])
                for pose in (0, 1)]
        theirs = [ic._composite(
            ic.dos_options(reference, "CBODY", size, pose)[body],
            ic.dos_options(reference, "CHEAD", size, pose)[head])
            for pose in (0, 1)]
        if mine != theirs:
            out.append(size)
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
             icon_colours: bytes, out: pathlib.Path,
             title: str = "pool-of-radiance",
             reference_game: pathlib.Path | None = None) -> None:
    """The proposal as a document, generated fresh from the YAML (#130).

    One PNG per figure rather than one sheet per table, because judging a
    row needs the C64 figure it is proposed as, beside the DOS figure it is
    proposed *for*, as its own image. The gallery at the end is every option
    the C64 offers, numbered, so a preferred alternative can be named.

    The loop is: edit `tools/iconproposal.yaml`, and run this again -- there
    is no reading a document back, because the YAML is the only place the
    numbers live.

    **`title`** is which of the three DOS titles' own game folder `game`
    holds; the default, Pool of Radiance, is the drawing every row of the
    table was chosen against, so its own document reads exactly as it
    always has, with nothing to compare. For the other two, pass
    `reference_game` -- Pool of Radiance's own game folder -- and every row
    says plainly whether this title draws the same figure or its own,
    measured against it rather than assumed (`#330`). The right-hand, C64
    picture is one picture regardless of title: `SPELLE64` and `SPELLN64`
    are the identical bytes in all three titles, so the same option tables
    on `disk` draw it for any of them.
    """
    weapons, heads = tables_for_title(title)
    display_title = games.by_key(title).title
    compare = reference_game is not None and reference_game != game
    parts = IconParts.load(str(disk))
    charset = icons.load_icon_charset(str(disk))
    img = out.parent / "img"
    lines = [
        f"# The proposed combat-figure table for {display_title}, for #130",
        "",
        "Each row is one DOS figure and the C64 figure it would become.",
        "**Edit `tools/iconproposal.yaml`** and run",
        f"`tools/iconproposal.py --title {title} --markdown {out}` to "
        f"redraw this document.",
        "The gallery at the end is every option the C64 offers.",
        "",
        "The DOS figure is drawn in its record's own colours and the C64 one",
        "in the colours that record converts to, so a row that looks wrong is",
        "wrong for the reason you can see.",
        "",
    ]
    redrawn_by_row: dict[tuple[str, int], list[str]] = {}
    if compare:
        for kind, table in (("weapon", weapons), ("head", heads)):
            for dos_index in table:
                sizes = redrawn_sizes(game, reference_game, kind, dos_index)
                if sizes:
                    redrawn_by_row[(kind, dos_index)] = sizes
        if redrawn_by_row:
            named = "; ".join(
                f"{kind} {dos_index} (at the {' and '.join(sizes)} size)"
                for (kind, dos_index), sizes in sorted(redrawn_by_row.items()))
            lines += [
                f"**{display_title} redraws its own art for "
                f"{len(redrawn_by_row)} of the rows below.** They are marked "
                f"plainly where they come up, with the extra picture that "
                f"shows the difference: {named}. Every other row is the "
                "same picture Pool of Radiance draws, and does not need "
                "judging again.",
                "",
            ]
        else:
            lines += [
                f"**Every row below is the same art Pool of Radiance "
                f"draws.** {display_title} ships the identical figures, "
                "measured block for block (#330), so no row here needs "
                "judging.",
                "",
            ]
        lines += [
            "The right-hand, C64 picture is one Pool of Radiance's own disk "
            "draws. Curse of the Azure Bonds and Secret of the Silver "
            "Blades ship the identical option tables, so it is the same "
            "picture either title's own disk would draw too (#330).",
            "",
        ]
    lines += [
        "This file and its images are the game's own art. They live under",
        "`work/` and must never be committed.",
        "",
    ]
    for kind, table, alternatives in (
            ("weapon", weapons, WEAPON_ALTERNATIVES),
            ("head", heads, HEAD_ALTERNATIVES)):
        lines += [f"## DOS {kind} to C64 {kind}", ""]
        if compare:
            lines += ["| DOS | | Match | Proposed | | Alternatives |",
                      "|---:|---|---|---:|---|---|"]
        else:
            lines += ["| DOS | | Proposed | | Alternatives |",
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
            cells = [str(dos_index), f"![](img/{name})"]
            if compare:
                sizes = redrawn_by_row.get((kind, dos_index), [])
                if sizes:
                    extra = []
                    for other in sizes:
                        if other != size:
                            oname = f"dos-{kind}-{other}-{dos_index:02d}.png"
                            save_figure(
                                dos_figure(game, other, body, head,
                                          icon_colours),
                                ic.EGA, img / oname)
                            extra.append(f"![]({'img/' + oname})")
                    cells.append(
                        f"**{display_title} redraws this figure**, at the "
                        f"{' and '.join(sizes)} size " + " ".join(extra))
                else:
                    cells.append("Same picture Pool of Radiance draws")
            cells += [str(c64_index),
                     f"![](img/{_c64_png(parts, charset, size, kind, c64_index, icon_colours, img)})",
                     " ".join(alts)]
            lines.append("| " + " | ".join(cells) + " |")
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


def title_dos_game(title: str, given: str | None,
                   archives: str | None) -> pathlib.Path:
    """`title`'s own DOS game folder.

    Pool of Radiance keeps `iconcorrespond.dos_game`'s own search -- `--dos`,
    then `$POR_DOS_GAME`, then the played copy at `~/dos_por_play`, then the
    archives -- unchanged, so the single-title tool this always was still
    works the same way with no `--title` given. Curse of the Azure Bonds and
    Secret of the Silver Blades have no played copy on this machine, so they
    are found the way `tools/dosicontitles.py` finds them: under the
    unpacked Forgotten Realms archives, `--archives` then `$FR_ARCHIVES` then
    `gamedisks.toml`'s `dos-archives` entry.
    """
    if given:
        return pathlib.Path(given).expanduser()
    if title == "pool-of-radiance":
        return ic.dos_game(None)
    return dit.find_folders(dit.archives(archives), [title])[title]


def reference_dos_game(archives: str | None) -> pathlib.Path:
    """Pool of Radiance's own game folder, to compare another title against
    (#330). Tried the same way `iconcorrespond.dos_game` always has, and only
    then under the archives, since a machine with no played copy still has to
    find one to compare against."""
    try:
        return ic.dos_game(None)
    except SystemExit:
        return dit.find_folders(dit.archives(archives),
                                ["pool-of-radiance"])["pool-of-radiance"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dos", help="the DOS game directory")
    ap.add_argument("--disk", help="POOL3.D64")
    ap.add_argument("--title", default="pool-of-radiance", choices=DOS_TITLES,
                    help="which DOS title's own art to draw; the C64 side "
                         "is one picture for all three (#330)")
    ap.add_argument("--archives", help="the unpacked Forgotten Realms "
                                       "archives, for a --title other than "
                                       "pool-of-radiance")
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
        game = title_dos_game(args.title, args.dos, args.archives)
        reference = (game if args.title == "pool-of-radiance"
                    else reference_dos_game(args.archives))
        markdown(game, ic.c64_disk(args.disk), args.size, colours,
                 pathlib.Path(args.markdown), title=args.title,
                 reference_game=reference)
    elif args.png:
        sheet(title_dos_game(args.title, args.dos, args.archives),
              ic.c64_disk(args.disk), args.kind, args.size, colours,
              pathlib.Path(args.png))
    else:
        print_tables()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
