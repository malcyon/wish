#!/usr/bin/env python3
"""Read the Amiga's character-creation portrait menu, and say how it differs.

`goldbox/portraits.py` carries two creation menus for Pool of Radiance: the
C64's and DOS's, which are one table byte for byte, and **the Amiga's, which
is that table with one entry changed** -- position 8 offers body art `0x05`
where the other two offer `0x18` (#194).  A number nobody can re-derive is a
number nobody can check, and this is how `AMIGA_POOL_OF_RADIANCE_MENU` is
re-derived:

    tools/amigaportraitmenu.py             # print the Amiga menu and the diff
    tools/amigaportraitmenu.py --check     # exit 1 if the disks disagree
    tools/amigaportraitmenu.py --art       # the art census behind the diff
    tools/amigaportraitmenu.py --palette   # the screen colours it draws in
    tools/amigaportraitmenu.py --montage work/issue194/menu.png

It finds the player's own Amiga disk images the way the other Amiga tools do
-- `tools/amigasaves.py`'s walk of `$AMIGA_DISKS` and `gamedisks.toml`, which
reads a loose `.adf` or one inside a zip -- takes `/program` off whichever
image carries it and `/head.dax` and `/body.dax` off whichever carries those,
and hands the three to `goldbox.portraits.tables_from_amiga`.  The table is
found by the shape of its run and every id in it checked against the art on
the disk beside it, so nothing here depends on a file offset.

`--art` is the evidence that the eighth body is a **different picture** and
not the same picture renumbered: it counts the distinct blocks in each port's
own head and body containers and names the ids that repeat.  The Amiga's
`body.dax` holds `0D`, `18` and `22` as one repeated block where DOS's `0D`
and `18` are one picture and its `22` another, so the Amiga ships 19 distinct
bodies of 21 ids where DOS ships 20 -- and the one it lost is the one its
menu stopped offering.

`--montage` draws the twelve menu bodies of each port in menu order, DOS on
the top row and the Amiga below, so the one that differs can be seen rather
than counted.  It needs Pillow and the DOS archives.

**The Amiga side is drawn through the game's own palette**, which is the
thirty-two words at the start of the `DATA` hunk the boot code copies one
word at a time into the screen's colour table; a four-bitplane portrait uses
the first sixteen.  An earlier version of this tool drew them through the EGA
palette and said so, which made the montage evidence about shape and not
about colour.  `--palette` prints the table and where it was read, and
`amiga_palette()` is what the drawing goes through now.

Every disk, executable and container is opened read-only, and the only thing
written is the file `--montage` names.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import amiga_dax, portraits  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from goldbox.dos_savegame import dax_block, dax_index  # noqa: E402

#: What the Amiga menu is read out of, and which disk each lives on.
WANTED = (portraits.AMIGA_PROGRAM, portraits.AMIGA_HEAD_DAX,
          portraits.AMIGA_BODY_DAX)


def amiga_files(roots=None) -> dict[str, tuple[str, bytes]]:
    """`name -> (where, bytes)` for `/program`, `/head.dax` and `/body.dax`.

    Every Amiga image on the machine is walked rather than a named one, so a
    release under a different filename still answers; the label records which
    image and which path each came from, because a reading that cannot be
    traced back to a file is not a measurement.
    """
    from tools import amigasaves

    out: dict[str, tuple[str, bytes]] = {}
    for label, image in amigasaves.images(roots):
        try:
            disk = AmigaDisk(image)
            paths = [path for path, _entry in disk.walk()]
        except (AmigaDiskError, ValueError):
            continue
        for path in paths:
            name = path.strip("/").split("/")[-1].lower()
            if name in WANTED and name not in out:
                try:
                    out[name] = (f"{label}:{path}", disk.read_file(path))
                except (AmigaDiskError, ValueError):
                    pass
        if len(out) == len(WANTED):
            break
    return out


def dos_blocks(game: pathlib.Path, stem: str) -> dict[int, bytes]:
    """Every block of a DOS `HEAD<n>.DAX` or `BODY<n>.DAX` set, by id."""
    out: dict[int, bytes] = {}
    for path in sorted(game.glob(f"{stem}[0-9].DAX")):
        data = path.read_bytes()
        for block_id, *_rest in dax_index(data, path.name):
            out.setdefault(block_id, dax_block(data, block_id, path.name))
    return out


def dos_game(given: str | None) -> pathlib.Path | None:
    if given:
        return pathlib.Path(given)
    try:
        from tools import dosbox
        return dosbox.find_game("POOLRAD")
    except (FileNotFoundError, ImportError):
        return None


def literal(tables: portraits.PortraitTables) -> str:
    """The table as the stored block in `goldbox/portraits.py` writes it."""
    def row(name, ids, per_line):
        chunks = [", ".join(f"0x{i:02X}" for i in ids[n:n + per_line])
                  for n in range(0, len(ids), per_line)]
        pad = " " * (len(name) + 2)
        return f"    {name}=(" + f",\n    {pad}".join(chunks) + "),"
    return "\n".join([row("heads", tables.heads, 7),
                      row("bodies", tables.bodies, 6)])


# ---------------------------------------------------------------------------
# The art census: distinct pictures behind the ids
# ---------------------------------------------------------------------------
def repeats(blocks: dict[int, bytes]) -> list[list[int]]:
    """The groups of ids that hold the same bytes, largest group first."""
    same: dict[str, list[int]] = {}
    for block_id, data in blocks.items():
        same.setdefault(hashlib.sha256(data).hexdigest(), []).append(block_id)
    return sorted((ids for ids in same.values() if len(ids) > 1),
                  key=len, reverse=True)


def report_art(out, files, game: pathlib.Path | None) -> int:
    """How many distinct pictures each port's containers actually hold."""
    rows: list[tuple[str, dict[int, bytes]]] = []
    for name, stem in ((portraits.AMIGA_HEAD_DAX, "HEAD"),
                       (portraits.AMIGA_BODY_DAX, "BODY")):
        data = files[name][1]
        rows.append((f"Amiga {name}",
                     {i: amiga_dax.block(data, i, name)
                      for i in amiga_dax.block_ids(data, name)}))
        if game is not None:
            rows.append((f"DOS {stem}<n>.DAX", dos_blocks(game, stem)))
    for label, blocks in rows:
        groups = repeats(blocks)
        out(f"{label}: {len(blocks)} ids, "
            f"{len(blocks) - sum(len(g) - 1 for g in groups)} distinct")
        for ids in groups:
            out("   one picture under " +
                ", ".join(f"{i:02X}" for i in sorted(ids)))
    return 0


# ---------------------------------------------------------------------------
# The montage
# ---------------------------------------------------------------------------
EGA = [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0),
       (170, 0, 170), (170, 85, 0), (170, 170, 170), (85, 85, 85),
       (85, 85, 255), (85, 255, 85), (85, 255, 255), (255, 85, 85),
       (255, 85, 255), (255, 255, 85), (255, 255, 255)]

#: How many colour words the boot code copies into the screen's colour table.
AMIGA_COLOURS = 32


class PaletteNotFound(ValueError):
    """This executable does not open its screen the way this reader knows."""


def _fetches_a_word_through(program: bytes, field: int) -> bool:
    """Is the `abs.l` field at `field` the table of a word-at-a-time copy?

    `lea.l table, a0` / `adda.l dn, a0` / `move.w (a0), dn` is what the boot
    code does thirty-two times, and it is what tells the palette apart from
    the other two `DATA` hunks here that also open with a run of small words.
    Both of those are indexed a **byte** at a time instead, so the shape of
    the fetch is the discriminator rather than the size of the table.
    """
    if program[field - 2:field] != b"\x41\xf9":            # lea.l abs.l, a0
        return False
    adda = int.from_bytes(program[field + 4:field + 6], "big")
    move = int.from_bytes(program[field + 6:field + 8], "big")
    return (0xD1C0 <= adda <= 0xD1C7            # adda.l dn, a0
            and move & 0xF1FF == 0x3010)        # move.w (a0), dn


def amiga_palette(program: bytes) -> tuple[int, list[tuple[int, int, int]]]:
    """`(file offset, RGB list)` for the screen palette `/program` installs.

    The table is the first thing in a `DATA` hunk and holds `AMIGA_COLOURS`
    big-endian `0RGB` words, each nibble a component.  Three of this
    executable's `DATA` hunks open with a run of small words, so the shape of
    the run is not enough on its own: the one that is taken is the one the
    code reads **a word at a time** through, which is `_fetches_a_word_
    through` above.  In the release read here that is the hunk at file offset
    `0x008AB0`, referenced once, from `0x002D1A`, inside a thirty-two
    iteration loop that writes each word into the open screen's colour table.

    Four-bitplane art -- every `head.dax` and `body.dax` block -- uses the
    first sixteen entries, so `amiga_image` indexes this list directly.
    """
    from tools import amiga68k

    exe = amiga68k.Executable.parse(program)

    def copied_a_word_at_a_time(hunk) -> bool:
        for (number, offset), to_hunk in exe.relocs.items():
            if to_hunk != hunk.number:
                continue
            field = exe.by_number(number).file_offset + offset
            # The stored addend is what gets added to the hunk's base, so a
            # nonzero one references something further into the hunk than its
            # first word.  The table is the hunk's first thing, so only a zero
            # addend can be the reference that reads it.
            if int.from_bytes(program[field:field + 4], "big"):
                continue
            if _fetches_a_word_through(program, field):
                return True
        return False

    found: list[tuple[int, list[int]]] = []
    for hunk in exe.hunks:
        if hunk.kind != "DATA" or hunk.file_offset is None:
            continue
        at = hunk.file_offset
        words = [int.from_bytes(program[at + 2 * i:at + 2 * i + 2], "big")
                 for i in range(AMIGA_COLOURS)]
        if len(words) < AMIGA_COLOURS or any(w > 0x0FFF for w in words):
            continue
        if not copied_a_word_at_a_time(hunk):
            continue
        found.append((at, words))

    if not found:
        raise PaletteNotFound(
            "no DATA hunk here opens with 32 colour words copied a word "
            "at a time")
    if len(found) > 1:
        # One release has been read and exactly one hunk qualifies.  A build
        # where two do is a release nobody has looked at, and taking whichever
        # iterated first would be the guess this function exists not to make.
        raise PaletteNotFound(
            "%d DATA hunks here open with 32 colour words copied a word at a "
            "time, at %s -- this release needs reading before one of them can "
            "be trusted"
            % (len(found), ", ".join("0x%06X" % at for at, _ in found)))

    at, words = found[0]
    return at, [(((w >> 8) & 15) * 17, ((w >> 4) & 15) * 17, (w & 15) * 17)
                for w in words]


def dos_image(block: bytes):
    """One DOS image block as a Pillow image: 17-byte header, 4-bit pixels."""
    from PIL import Image

    rows, eights = block[0], block[2]
    image = Image.new("RGB", (eights * 8, rows))
    at = 17
    for row in range(rows):
        for i in range(eights * 4):
            value = block[at]
            at += 1
            image.putpixel((i * 2, row), EGA[value >> 4])
            image.putpixel((i * 2 + 1, row), EGA[value & 15])
    return image


def amiga_image(block: bytes, palette=None):
    """One Amiga `.dax` image block: a 12-byte header and four bitplanes.

    The header is the DOS one -- rows, width in eights -- with a leading pad
    byte and the plane's size in bytes appended, and the four planes follow
    one whole plane at a time.  `palette` is what `amiga_palette` read out of
    the player's own executable; the EGA palette is the fallback and is not
    the Amiga's, so a caller that has the program file should pass one.
    """
    from PIL import Image

    if palette is None:
        palette = EGA
    rows, eights = block[1], block[3]
    plane = (block[10] << 8) | block[11]
    stride = plane // rows
    image = Image.new("RGB", (eights * 8, rows))
    for row in range(rows):
        pixels = [0] * (stride * 8)
        for p in range(4):
            base = 12 + p * plane + row * stride
            for i in range(stride):
                value = block[base + i]
                for bit in range(8):
                    if value & (0x80 >> bit):
                        pixels[i * 8 + bit] |= 1 << p
        for column in range(eights * 8):
            image.putpixel((column, row), palette[pixels[column]])
    return image


def montage(path: pathlib.Path, files, game: pathlib.Path, kind: str,
            scale: int = 2) -> None:
    """The menu drawn in menu order, DOS on top and the Amiga below."""
    from PIL import Image

    _at, palette = amiga_palette(files[portraits.AMIGA_PROGRAM][1])

    stem, name, table = (
        ("BODY", portraits.AMIGA_BODY_DAX, "bodies") if kind == "body"
        else ("HEAD", portraits.AMIGA_HEAD_DAX, "heads"))
    dos = dos_blocks(game, stem)
    art = files[name][1]
    dos_ids = getattr(portraits.POOL_OF_RADIANCE_MENU, table)
    amiga_ids = getattr(portraits.AMIGA_POOL_OF_RADIANCE_MENU, table)
    first = dos_image(dos[dos_ids[0]])
    width, height = first.size
    sheet = Image.new("RGB", (width * scale * len(dos_ids),
                              height * scale * 2 + 8), (20, 20, 20))
    for i, (a, b) in enumerate(zip(dos_ids, amiga_ids)):
        top = dos_image(dos[a]).resize((width * scale, height * scale),
                                       Image.NEAREST)
        low = amiga_image(amiga_dax.block(art, b, name), palette).resize(
            (width * scale, height * scale), Image.NEAREST)
        sheet.paste(top, (i * width * scale, 0))
        sheet.paste(low, (i * width * scale, height * scale + 8))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--disks", help="a folder of Amiga .adf images to use "
                                    "instead of the machine's own list")
    ap.add_argument("--dos", help="the DOS Pool of Radiance game directory, "
                                  "for --art and --montage")
    ap.add_argument("--check", action="store_true",
                    help="compare the reading with the stored Amiga menu and "
                         "exit 1 on a disagreement")
    ap.add_argument("--art", action="store_true",
                    help="count the distinct pictures behind each port's ids")
    ap.add_argument("--palette", action="store_true",
                    help="print the screen palette the executable installs")
    ap.add_argument("--montage", help="write the twelve menu bodies of both "
                                      "ports to this PNG")
    ap.add_argument("--montage-kind", choices=("body", "head"), default="body")
    args = ap.parse_args(argv)

    def out(line: str) -> None:
        print(line)

    roots = [pathlib.Path(args.disks)] if args.disks else None
    files = amiga_files(roots)
    missing = [name for name in WANTED if name not in files]
    if missing:
        out(f"No Amiga Pool of Radiance disk here carries "
            f"{', '.join(missing)}; set AMIGA_DISKS or pass --disks.")
        return 2

    tables = portraits.tables_from_amiga(
        files[portraits.AMIGA_PROGRAM][1],
        files[portraits.AMIGA_HEAD_DAX][1],
        files[portraits.AMIGA_BODY_DAX][1],
        files[portraits.AMIGA_PROGRAM][0])
    for name in WANTED:
        where, data = files[name]
        out(f"{name:<10} {where}  {len(data)} bytes  "
            f"sha256 {hashlib.sha256(data).hexdigest()[:16]}")
    out(f"menu at {tables.source}")
    out(literal(tables))

    stored = portraits.stored_tables(port=portraits.AMIGA_PORT)
    shared = portraits.stored_tables()
    status = 0
    for label, other in (("the stored Amiga menu", stored),
                         ("the C64's and DOS's menu", shared)):
        rows = tables.differences(other)
        if not rows:
            out(f"agrees with {label}")
            continue
        out(f"differs from {label}:")
        for what, position, mine, theirs in rows:
            out(f"   {what} position {position}: "
                f"the Amiga offers art 0x{mine:02X}, "
                f"the other 0x{theirs:02X}")
        if other is stored and args.check:
            status = 1

    if args.palette:
        try:
            at, colours = amiga_palette(files[portraits.AMIGA_PROGRAM][1])
        except PaletteNotFound as e:
            out(str(e)[0].upper() + str(e)[1:])
            return 2
        out(f"screen palette at file offset 0x{at:06X}, "
            f"{len(colours)} entries; the first sixteen are what a "
            f"four-bitplane portrait uses")
        for base in range(0, len(colours), 8):
            out("   " + "  ".join(
                f"{base + n:2d} {r // 17:X}{g // 17:X}{b // 17:X}"
                for n, (r, g, b) in enumerate(colours[base:base + 8])))

    game = dos_game(args.dos)
    if args.art:
        if game is None:
            out("no DOS game directory found, so the census is the Amiga's "
                "alone; set FR_ARCHIVES or pass --dos")
        report_art(out, files, game)
    if args.montage:
        if game is None:
            out("--montage needs the DOS art as well; set FR_ARCHIVES or "
                "pass --dos")
            return 2
        try:
            montage(pathlib.Path(args.montage), files, game,
                    args.montage_kind)
        except PaletteNotFound as e:
            out(str(e)[0].upper() + str(e)[1:])
            return 2
        out(f"wrote {args.montage}: DOS on the top row, the Amiga below")
    return status


if __name__ == "__main__":
    sys.exit(main())
