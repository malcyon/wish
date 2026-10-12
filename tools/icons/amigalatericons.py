#!/usr/bin/env python3
"""Draw an Amiga Curse or Silver Blades character's combat figure off the
player's own disks, and check it against a capture of the game's ICON screen.

``--palette``
    Each title's recolour tables, read out of its executable, and the sixteen
    colours its ICON screen shows, read out of its `ALWAYS.TLB`.

``--compose NAME``
    The named character's ready and action poses as palette entries, `.`
    where the box behind shows through.

``--capture NAME PNG``
    Where the named character's two poses, drawn over their boxes, appear
    pixel for pixel in a canonical WinUAE crop (every Amiga pixel a 2x2
    block).  Exits 1 unless each pose is found at least once.

    tools/icons/amigalatericons.py --palette
    tools/icons/amigalatericons.py --compose GALAIN
    tools/icons/amigalatericons.py --capture GALAIN galain-icon-crop.png

`goldbox/amiga_later_icons.py` holds the rules and
`docs/199-amiga-combat-icons.md` the write-up.  Every disk is opened
read-only and nothing of the game's is written anywhere.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import amiga_later_icons as later  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402


def disks() -> list[AmigaDisk]:
    """Every readable Amiga disk image on this machine."""
    from tools.amiga import amigasaves
    out = []
    for _label, image in amigasaves.images():
        try:
            disk = AmigaDisk(image)
            list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        out.append(disk)
    return out


def title_art(title: str, opened: list[AmigaDisk] | None = None
              ) -> later.LaterArt | None:
    """The title's figure art off this machine's disks.

    None when a file it needs is not on any disk here; any other
    :class:`later.LaterArtError` -- a file that is there and cannot be
    read -- is raised, not hidden.
    """
    try:
        return later.read_art(title, later.disk_files(
            title, disks() if opened is None else opened))
    except later.LaterArtMissing:
        return None


def _art_or_report(out, title: str, opened=None) -> later.LaterArt | None:
    """:func:`title_art`, with what went wrong printed rather than raised."""
    try:
        art = title_art(title, opened)
    except later.LaterArtError as exc:
        out(f"{title}: {exc}")
        return None
    if art is None:
        out(f"{title}: its disks are not all on this machine")
    return art


def records() -> list:
    """Every Amiga Curse and Silver Blades character on this machine."""
    from goldbox import amiga_later, amiga_port
    from tools.amiga import amigarecords
    out = []
    with tempfile.TemporaryDirectory(prefix="amigalatericons-") as tmp:
        for path in amigarecords.extract(pathlib.Path(tmp)):
            if path.suffix == ".guy":
                out.append(amiga_later.read_amiga_guy(path))
            elif path.name.startswith("CurseA-savgam"):
                out += amiga_later.party_in_savegame(
                    path.read_bytes(), amiga_port.CURSE_DELTAS)
            elif path.name.startswith("Secret1-savgam"):
                out += amiga_later.party_in_savegame(
                    path.read_bytes(), amiga_port.SILVER_BLADES_DELTAS)
    return out


def find_record(name: str):
    """The first character called `name`, any case, or None."""
    return next((c for c in records()
                 if (getattr(c, "name", "") or "").strip().upper()
                 == name.strip().upper()), None)


def _fields(char) -> tuple[int, int, int, bytes]:
    return (char.get("icon_head"), char.get("icon_body"), char.get("size"),
            bytes(char.get("icon_colours")))


def report_palette(out) -> int:
    problems = 0
    opened = disks()
    for title in later.TITLES:
        art = _art_or_report(out, title, opened)
        if art is None:
            problems += 1
            continue
        out(f"{title}")
        out(f"  DOS value -> palette entry: {art.entry.hex(' ')}")
        out(f"  recoloured parts:           {art.parts.hex(' ')}")
        out(f"  load table:                 {art.load.hex(' ')}")
        out(f"  ICON palette (ALWAYS.TLB block "
            f"{later.TITLES[title].palette_block}): "
            + " ".join(f"{r // 17:x}{g // 17:x}{b // 17:x}"
                       for r, g, b in art.palette))
    return problems


def report_compose(out, name: str) -> int:
    char = find_record(name)
    if char is None:
        out(f"no Amiga Curse or Silver Blades character called {name}")
        return 1
    art = _art_or_report(out, char.deltas.dos.key)
    if art is None:
        return 1
    title = char.deltas.dos.key
    head, body, size, colours = _fields(char)
    out(f"{char.name}  {title}  head {head} body {body} size {size} "
        f"colours {colours.hex(' ')}")
    for label, pose in zip(("ready", "action"),
                           art.poses(head, body, size, colours)):
        out(f"  {label}")
        for row in pose:
            out("    " + "".join("." if v is None else f"{v:x}" for v in row))
    return 0


def compare_capture(name: str, path) -> dict[str, tuple] | None:
    """`{"ready": (places, fewest differing), "action": ...}`, or None when
    the record or the art is not on this machine."""
    from tools.icons.amigaporicons import capture_pixels, find_pose
    char = find_record(name)
    if char is None:
        return None
    art = title_art(char.deltas.dos.key)
    if art is None:
        return None
    screen = capture_pixels(path)
    ready, action = art.drawn(*_fields(char))
    return {"ready": find_pose(screen, ready),
            "action": find_pose(screen, action)}


def report_capture(out, name: str, path) -> int:
    try:
        found = compare_capture(name, path)
    except later.LaterArtError as exc:
        out(f"{name}: {exc}")
        return 1
    if found is None:
        out(f"no {name}, or not all of that title's disks, on this machine")
        return 1
    problems = 0
    for pose, (places, fewest) in found.items():
        if places:
            out(f"{name} {pose}: matches pixel for pixel at "
                + ", ".join(f"({x}, {y})" for x, y in places))
        else:
            out(f"{name} {pose}: no exact match; the closest differs in "
                f"{fewest} of {later.CELL * later.CELL} pixels")
            problems += 1
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--palette", action="store_true",
                        help="the recolour tables and ICON palette")
    parser.add_argument("--compose", metavar="NAME",
                        help="a character's two poses as palette entries")
    parser.add_argument("--capture", nargs=2, metavar=("NAME", "PNG"),
                        help="find a character's poses in an ICON capture")
    args = parser.parse_args(argv)
    if not (args.palette or args.compose or args.capture):
        parser.error("say which: --palette, --compose NAME or --capture "
                     "NAME PNG")
    problems = 0
    if args.palette:
        problems += report_palette(print)
    if args.compose:
        problems += report_compose(print, args.compose)
    if args.capture:
        problems += report_capture(print, *args.capture)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
