#!/usr/bin/env python3
"""Measure the Amiga Pool of Radiance combat-figure art against DOS's own.

The Amiga Pool art is `/chead.dax` and `/cbody.dax` on disk 2 (`POOLDATA`),
read by `goldbox/amiga_por_icons.py`.  This compares it with DOS Pool of
Radiance's `CHEAD.DAX` and `CBODY.DAX`, pixel for pixel through
`goldbox.amiga_por_icons.DOS_TO_AMIGA`.

``--art``
    Every Amiga block: the DOS block it is pixel for pixel (at the same id or
    another), or the nearest DOS block of the same size and how many pixels
    differ.

``--table``
    The same comparison by menu option: for each size, which DOS `icon_head`
    or `icon_body` draws the Amiga option's picture in both poses, and the C64
    option that DOS number converts to through `tools/icons/iconproposal.yaml`.
    Markdown, for a ticket.

``--code``
    The two tables the preparer reads out of `/program`: the size letters and
    the six recoloured pairs, against the constants the module holds.

``--sweep``
    The icon fields of every Amiga Pool character file on the player's disks,
    and the blocks each names.

``--palette``
    The ICON screen's sixteen colours, found in `/program` by
    `goldbox.amiga_por_icons.icon_palette_chain`, with the four offsets of
    the chain that installs them.

``--capture NAME PNG``
    Compose NAME's two poses from the record on the player's disks, draw each
    over the ICON screen's box in the ICON palette, and look for it in PNG, a
    720x568 crop of the game's own ICON screen (`tools.amiga.screens`
    canonical, each Amiga pixel doubled).  Prints where each pose matches
    pixel for pixel, or the fewest pixels any place differs by.

    tools/icons/amigaporicons.py --art
    tools/icons/amigaporicons.py --table
    tools/icons/amigaporicons.py --code --sweep --palette
    tools/icons/amigaporicons.py --capture LAURANN laurann-icon-crop.png

Every disk is opened read-only and nothing is written.  The write-up is
`docs/240-amiga-pool-combat-figure.md`.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import amiga_por_icons as art  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools.icons.amigaicons import dos_directory, dos_tiles  # noqa: E402

#: How many options the ICON menu offers: DOS's fourteen heads and
#: thirty-two bodies, and the libraries hold blocks for exactly those.
HEAD_OPTIONS, BODY_OPTIONS = 14, 32

#: `/program` file offsets of the size letters and the six source pairs, in
#: the one build on the player's disks, whose SHA-256 is `PROGRAM_SHA256`.
#: Another build may keep them elsewhere, so `--code` reads them only there.
LETTERS_AT, PAIRS_AT = 0x02C713, 0x06DD4F
PROGRAM_SHA256 = ("b1cbbecc01889c16fe0b6048b6f70126"
                  "97d2bf0b7b5e0408971d758a0def91d1")

#: A figure block is this many Amiga pixels square.
FIGURE = 24


def _images():
    from tools.amiga import amigasaves
    return amigasaves.images()


def find_files(wanted: tuple[str, ...]) -> tuple[str, dict[str, bytes]] | None:
    """`(label, {name: bytes})` off the first Amiga disk holding all `wanted`."""
    for label, image in _images():
        try:
            disk = AmigaDisk(image)
            names = {path.strip("/").lower(): path for path, _ in disk.walk()}
        except (AmigaDiskError, ValueError):
            continue
        if all(name in names for name in wanted):
            try:
                return label, {name: disk.read_file(names[name])
                               for name in wanted}
            except AmigaDiskError:
                continue
    return None


def amiga_art() -> dict[str, dict[int, art.ArtBlock]] | None:
    """`{"head": blocks, "body": blocks, "frame": blocks}` off disk 2, or None.

    `"frame"` is `comspr.dax`, whose block `art.FRAME_BLOCK` is the ICON
    screen's box.
    """
    found = find_files((art.HEAD_FILE, art.BODY_FILE, art.FRAME_FILE))
    if found is None:
        return None
    files = found[1]
    return {"head": art.read_art(files[art.HEAD_FILE], art.HEAD_FILE),
            "body": art.read_art(files[art.BODY_FILE], art.BODY_FILE),
            "frame": art.read_art(files[art.FRAME_FILE], art.FRAME_FILE)}


def program() -> bytes | None:
    """`/program` off the player's disk 1, or None."""
    found = find_files(("program",))
    return None if found is None else found[1]["program"]


def dos_art(translate: bool = True) -> dict[str, dict[int, tuple]] | None:
    """DOS Pool's blocks as `{kind: {id: rows}}`, through `DOS_TO_AMIGA`."""
    where = dos_directory("POOLRAD")
    if where is None:
        return None
    out = {}
    for kind, name in (("head", "CHEAD.DAX"), ("body", "CBODY.DAX")):
        out[kind] = {
            bid: tuple(tuple(art.DOS_TO_AMIGA[v] if translate else v
                             for v in row) for row in rows)
            for bid, (_h, _w, rows) in dos_tiles(where / name).items()}
    return out


def difference(a, b) -> int | None:
    """Pixels that differ between two pictures, or None if sizes differ."""
    if len(a) != len(b) or any(len(x) != len(y) for x, y in zip(a, b)):
        return None
    return sum(p != q for x, y in zip(a, b) for p, q in zip(x, y))


def classify(amiga, dos) -> dict[str, dict[int, tuple]]:
    """Per kind, `id -> ("same"|"other", [dos ids])` or `("none", (n, id))`."""
    out = {}
    for kind in ("head", "body"):
        out[kind] = {}
        for bid, block in sorted(amiga[kind].items()):
            exact = sorted(d for d, rows in dos[kind].items()
                           if rows == block.rows)
            if bid in exact:
                out[kind][bid] = ("same", exact)
            elif exact:
                out[kind][bid] = ("other", exact)
            else:
                near = min((n, d) for d, rows in dos[kind].items()
                           if (n := difference(block.rows, rows)) is not None)
                out[kind][bid] = ("none", near)
    return out


def counts(classes) -> dict[str, tuple[int, int, int]]:
    """Per kind, `(exact at any id, exact at the same id, no exact)`."""
    out = {}
    for kind, rows in classes.items():
        same = sum(1 for c, _ in rows.values() if c == "same")
        other = sum(1 for c, _ in rows.values() if c == "other")
        out[kind] = (same + other, same, len(rows) - same - other)
    return out


def option_table(amiga, dos, kind: str, size: int) -> list[tuple]:
    """`(option, dos option or None, nearest, pixels)` for one kind and size.

    An Amiga option has a DOS equivalent when one DOS option of the same size
    draws both its poses pixel for pixel; otherwise `nearest` is the DOS
    option of that size with the fewest differing pixels over both poses.
    """
    limit = HEAD_OPTIONS if kind == "head" else BODY_OPTIONS
    rows = []
    for option in range(limit):
        mine = art.block_ids(kind, option, size)
        scores = []
        for other in range(limit):
            theirs = art.block_ids(kind, other, size)
            total = 0
            for a, d in zip(mine, theirs):
                n = difference(amiga[kind][a].rows, dos[kind][d])
                total += 10_000 if n is None else n
            scores.append((total, other))
        best, nearest = min(scores)
        rows.append((option, nearest if best == 0 else None, nearest, best))
    return rows


def c64_tables():
    from goldbox.iconparts import dos_icon_tables
    return {size: dos_icon_tables(title="pool-of-radiance", size=name)
            for size, name in ((1, "small"), (2, "large"))}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def report_art(out) -> int:
    amiga, dos = amiga_art(), dos_art()
    if amiga is None or dos is None:
        out("need POOLDATA's chead.dax and cbody.dax and DOS POOLRAD")
        return 1
    classes = classify(amiga, dos)
    for kind, rows in classes.items():
        for bid, (what, detail) in rows.items():
            if what == "none":
                out(f"{kind} {bid:3d}: no DOS counterpart; nearest DOS "
                    f"{detail[1]}, {detail[0]} pixels differ")
            else:
                out(f"{kind} {bid:3d}: DOS {', '.join(map(str, detail))}"
                    + (" (same id)" if what == "same" else ""))
    for kind, (exact, same, none) in counts(classes).items():
        out(f"{kind}: {len(classes[kind])} blocks, {exact} pixel for pixel "
            f"a DOS block ({same} at the same id), {none} with no DOS "
            f"counterpart")
    return 0


def report_table(out) -> int:
    amiga, dos = amiga_art(), dos_art()
    if amiga is None or dos is None:
        out("need POOLDATA's chead.dax and cbody.dax and DOS POOLRAD")
        return 1
    c64 = c64_tables()
    for kind in ("head", "body"):
        for size in (1, 2):
            out(f"\n{kind} options, size {size}\n")
            out("| Amiga | DOS | C64 | nearest DOS, pixels differing |")
            out("|---|---|---|---|")
            table = c64[size].heads if kind == "head" else c64[size].weapons
            for option, same, nearest, pixels in option_table(
                    amiga, dos, kind, size):
                if same is None:
                    out(f"| {option} | none | none | {nearest}, {pixels} |")
                else:
                    out(f"| {option} | {same} | {table.get(same, '?')} | |")
    return 0


def report_code(out) -> int:
    found = find_files(("program",))
    if found is None:
        out("no /program on any Amiga disk here")
        return 1
    program = found[1]["program"]
    digest = hashlib.sha256(program).hexdigest()
    out(f"/program sha256 {digest[:16]}...")
    if digest != PROGRAM_SHA256:
        out(f"  not the build the offsets were read from "
            f"({PROGRAM_SHA256[:16]}...); nothing compared")
        return 1
    letters = program[LETTERS_AT:LETTERS_AT + 3]
    pairs = program[PAIRS_AT:PAIRS_AT + 6]
    out(f"  size letters at 0x{LETTERS_AT:06X}: {letters!r}")
    out(f"  source pairs at 0x{PAIRS_AT:06X}: {pairs.hex(' ')}")
    problems = 0
    if letters[1:3].decode("latin1") != "".join(art.SIZE_LETTERS.values()):
        out("  the size letters are not the module's")
        problems += 1
    if pairs != art.SOURCE_PAIRS:
        out("  the source pairs are not the module's")
        problems += 1
    return problems


def report_sweep(out) -> int:
    from goldbox.amiga_por import AmigaPorCharacter
    from tools.amiga import amigasaves
    amiga = amiga_art()
    records, seen = [], set()
    for _label, volume, name, files in amigasaves.specimens():
        record = next(v for k, v in files.items()
                      if len(v) == 288 and not k.lower().endswith(
                          (".itm", ".spc")))
        if record in seen:
            continue
        seen.add(record)
        records.append((volume, name, AmigaPorCharacter.from_bytes(record)))
    if not records:
        out("no Amiga Pool of Radiance character files here")
        return 1
    problems = 0
    out(f"{'volume':<10} {'file':<16} {'name':<16} head body size  colours"
        f"            blocks")
    for volume, name, char in records:
        head, body = char.get("icon_head"), char.get("icon_body")
        size, colours = char.get("size"), bytes(char.get("icon_colours"))
        heads = art.block_ids("head", head, size)
        bodies = art.block_ids("body", body, size)
        out(f"{volume:<10} {name:<16} {char.name:<16} {head:4d} {body:4d} "
            f"{size:4d}  {colours.hex(' ')}  head {heads[0]}, "
            f"body {bodies[0]}/{bodies[1]}")
        if amiga is not None:
            missing = ([b for b in heads if b not in amiga["head"]]
                       + [b for b in bodies if b not in amiga["body"]])
            if missing:
                out(f"    names blocks the art does not hold: {missing}")
                problems += 1
    out(f"{len(records)} distinct records")
    return problems


def report_palette(out) -> int:
    code = program()
    if code is None:
        out("no /program on any Amiga disk here")
        return 1
    try:
        bar, call, setter, table = art.icon_palette_chain(code)
    except art.PorArtError as exc:
        out(str(exc))
        return 1
    out(f"ICON bar loaded at 0x{bar:06X}, setter called at 0x{call:06X}, "
        f"setter 0x{setter:06X}, table 0x{table:06X}")
    for value, rgb in enumerate(art.icon_palette(code)):
        out(f"  {value:2d}  #{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}")
    return 0


def find_record(name: str):
    """The first Amiga Pool character called `name` on the player's disks."""
    from goldbox.amiga_por import AmigaPorCharacter
    from tools.amiga import amigasaves
    for _label, _volume, _file, files in amigasaves.specimens():
        record = next((v for k, v in files.items() if len(v) == 288
                       and not k.lower().endswith((".itm", ".spc"))), None)
        if record is None:
            continue
        char = AmigaPorCharacter.from_bytes(record)
        if char.name == name:
            return char
    return None


def drawn_poses(char, amiga, code) -> tuple[tuple, tuple]:
    """`char`'s ready and action poses over the ICON box, as rows of RGB."""
    palette = art.icon_palette(code)
    frame = amiga["frame"][art.FRAME_BLOCK]
    poses = art.compose(amiga["head"], amiga["body"], char.get("icon_head"),
                        char.get("icon_body"), char.get("size"),
                        bytes(char.get("icon_colours")))
    return tuple(tuple(tuple(palette[v] for v in row)
                       for row in art.on_frame(frame, pose))
                 for pose in poses)


def capture_pixels(path):
    """A canonical crop's Amiga pixels, `(rows, columns)` of packed RGB.

    Raises `ValueError` unless every 2x2 block of the crop is one colour,
    which a resampled or filtered frame would not be.
    """
    import numpy
    from PIL import Image
    with Image.open(path) as image:
        rgb = numpy.asarray(image.convert("RGB"), dtype=numpy.int32)
    if rgb.shape[0] % 2 or rgb.shape[1] % 2:
        raise ValueError(f"{path}: {rgb.shape[1]}x{rgb.shape[0]} is not "
                         f"a doubled frame")
    packed = rgb[..., 0] << 16 | rgb[..., 1] << 8 | rgb[..., 2]
    small = packed[::2, ::2]
    for dy in (0, 1):
        for dx in (0, 1):
            if not numpy.array_equal(packed[dy::2, dx::2], small):
                raise ValueError(f"{path}: not every Amiga pixel is a "
                                 f"single-colour 2x2 block")
    return small


def find_pose(screen, pose) -> tuple[list[tuple[int, int]], int]:
    """`(places matching pixel for pixel, fewest pixels differing anywhere)`.

    Places are the `(x, y)` of the pose's top-left corner in Amiga pixels.
    """
    import numpy
    from numpy.lib.stride_tricks import sliding_window_view
    want = numpy.array([[r << 16 | g << 8 | b for r, g, b in row]
                        for row in pose], dtype=numpy.int32)
    windows = sliding_window_view(screen, want.shape)
    differ = (windows != want).sum(axis=(2, 3))
    ys, xs = numpy.nonzero(differ == 0)
    return sorted(zip(xs.tolist(), ys.tolist())), int(differ.min())


def compare_capture(name: str, path) -> dict[str, tuple] | None:
    """`{"ready": find_pose(...), "action": ...}` for `name` in `path`.

    None when the art, `/program` or the record is not on this machine.
    """
    amiga, code, char = amiga_art(), program(), find_record(name)
    if amiga is None or code is None or char is None:
        return None
    screen = capture_pixels(path)
    ready, action = drawn_poses(char, amiga, code)
    return {"ready": find_pose(screen, ready),
            "action": find_pose(screen, action)}


def report_capture(out, name: str, path) -> int:
    found = compare_capture(name, path)
    if found is None:
        out(f"need POOLDATA's art, /program and a record called {name}")
        return 1
    problems = 0
    for pose, (places, fewest) in found.items():
        if places:
            out(f"{name} {pose}: pixel for pixel at "
                + ", ".join(f"({x}, {y})" for x, y in places))
        else:
            out(f"{name} {pose}: nowhere; the closest place differs in "
                f"{fewest} of {FIGURE * FIGURE} pixels")
            problems += 1
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--art", action="store_true",
                        help="every Amiga block against the DOS blocks")
    parser.add_argument("--table", action="store_true",
                        help="Amiga option to DOS and C64 option, Markdown")
    parser.add_argument("--code", action="store_true",
                        help="the preparer's two tables out of /program")
    parser.add_argument("--sweep", action="store_true",
                        help="every Amiga Pool character's icon fields")
    parser.add_argument("--palette", action="store_true",
                        help="the ICON screen's colours out of /program")
    parser.add_argument("--capture", nargs=2, metavar=("NAME", "PNG"),
                        help="NAME's composed figure against an ICON crop")
    args = parser.parse_args(argv)
    if not (args.art or args.table or args.code or args.sweep
            or args.palette or args.capture):
        parser.error("say which: --art, --table, --code, --sweep, "
                     "--palette or --capture")
    problems = 0
    if args.art:
        problems += report_art(print)
    if args.table:
        problems += report_table(print)
    if args.code:
        problems += report_code(print)
    if args.sweep:
        problems += report_sweep(print)
    if args.palette:
        problems += report_palette(print)
    if args.capture:
        problems += report_capture(print, *args.capture)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
