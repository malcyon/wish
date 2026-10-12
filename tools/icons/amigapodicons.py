#!/usr/bin/env python3
"""Draw an Amiga Pools of Darkness character's combat figure off the
player's own disks, and check it against a capture of the game's ICON screen.

``--palette``
    The recolour tables, read out of `/Pools of Darkness`, and the 32
    colours the ICON screen shows, read out of `ALWAYS.TLB` block 0.

``--dos``
    Every head and body tile against DOS Pools of Darkness's block of the
    same id, through the entry table: how many are equal, and which DOS
    value and Amiga entry each differing pixel holds.

``--sweep``
    Every character on this machine's disk 3 images, composed over the
    boxes: one line each.

``--compose NAME``
    The named character's ready and action poses as palette entries, `.`
    where the box behind shows through.

``--capture NAME PNG``
    Where the named character's two poses, drawn over their boxes, appear
    pixel for pixel in a canonical WinUAE crop (every Amiga pixel a 2x2
    block).  Exits 1 unless each pose is found at least once.  `--disk3
    ADF --slot L` reads the character from that saved game, the run's own
    disk, instead of the first one of that name here.

    tools/icons/amigapodicons.py --palette
    tools/icons/amigapodicons.py --compose goofey
    tools/icons/amigapodicons.py --capture goofey goofey-icon-crop.png \\
        --disk3 run/disk3.adf --slot B

`goldbox/amiga_pod_icons.py` holds the rules and
`docs/199-amiga-combat-icons.md` the write-up.  Every disk is opened
read-only and nothing of the game's is written anywhere.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import amiga_later_icons as later  # noqa: E402
from goldbox import amiga_pod  # noqa: E402
from goldbox import amiga_pod_icons as pod  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402


@dataclass(frozen=True)
class Record:
    """One character's figure fields and where they were read."""

    where: str
    name: str
    head: int
    body: int
    size: int
    colours: bytes

    @property
    def fields(self) -> tuple[int, int, int, bytes]:
        return self.head, self.body, self.size, self.colours


def disks() -> list[AmigaDisk]:
    """Every readable Amiga disk image on this machine."""
    from tools.icons import amigalatericons
    return amigalatericons.disks()


def art(opened: list[AmigaDisk] | None = None) -> later.LaterArt | None:
    """The figure art off this machine's disks, or None when a file it
    needs is not on any of them; a file that is there and cannot be read
    raises :class:`later.LaterArtError`."""
    try:
        return pod.read_art(pod.disk_files(
            disks() if opened is None else opened))
    except later.LaterArtMissing:
        return None


def _record(where: str, raw: bytes, name: str) -> Record:
    colours = amiga_pod.ICON_COLOURS
    return Record(where, name.strip(), raw[amiga_pod.ICON_HEAD],
                  raw[amiga_pod.ICON_BODY], raw[amiga_pod.SIZE],
                  bytes(raw[colours:colours + amiga_pod.ICON_COLOUR_COUNT]))


def disk_records(disk: AmigaDisk, label: str = "",
                 slot: str | None = None) -> list[Record]:
    """The characters of a disk 3's saved games and `.pc` files, or of
    slot `slot`'s saved game alone."""
    from goldbox import amiga_savegame as saves
    out = []
    letters = saves.pod_slots_present(disk)
    if slot is not None:
        letters = [saves.slot_letter(slot)] if saves.slot_letter(
            slot) in letters else []
    for letter in letters:
        data = saves.pod_read_slot(disk, letter)
        for block in saves.pod_parse(data).characters:
            out.append(_record(f"{label} slot {letter}",
                               data[block.at:block.at
                                    + saves.POD_RECORD_BYTES], block.name))
    if slot is not None:
        return out
    for path, _entry in disk.walk():
        parts = path.strip("/").split("/")
        if (len(parts) != 2 or parts[0].upper() != "SAVE"
                or not parts[1].upper().endswith(".PC")):
            continue
        try:
            char = amiga_pod.PodCharacter.from_bytes(disk.read_file(path))
        except (AmigaDiskError, ValueError):
            continue
        out.append(_record(f"{label} {path}", char.raw, char.name))
    return out


def records(opened: list[AmigaDisk] | None = None) -> list[Record]:
    """Every Amiga Pools of Darkness character on this machine's disks."""
    out = []
    for disk in disks() if opened is None else opened:
        try:
            if disk.volume_name != "POD 3":
                continue
            out += disk_records(disk, disk.volume_name)
        except (AmigaDiskError, ValueError):
            continue
    return out


def find_record(name: str, found: list[Record] | None = None
                ) -> Record | None:
    """The first character called `name`, any case and trailing spaces."""
    want = name.strip().upper()
    return next((r for r in (records() if found is None else found)
                 if r.name.upper() == want), None)


def report_palette(out) -> int:
    drawn = art()
    if drawn is None:
        out("pools-of-darkness: its disks are not all on this machine")
        return 1
    out("pools-of-darkness")
    out(f"  DOS value -> palette entry: {drawn.entry.hex(' ')}")
    out(f"  recoloured parts:           {drawn.parts.hex(' ')}")
    out(f"  ICON palette (ALWAYS.TLB block {pod.PALETTE_BLOCK}): "
        + " ".join(f"{r // 17:x}{g // 17:x}{b // 17:x}"
                   for r, g, b in drawn.palette))
    return 0


def dos_differences(drawn: later.LaterArt, dos) -> dict:
    """`{"equal": n, "tiles": [...], "pairs": Counter}` of every Amiga head
    and body tile against DOS's block of the same id (`dos`, a
    `goldbox.dos_pod_icons.PodGameArt`), mapped through the entry table."""
    from goldbox import dos_pod_icons
    equal, tiles, pairs = 0, [], collections.Counter()
    for kind, amiga, blocks in (("head", drawn.heads, dos.heads),
                                ("body", drawn.bodies, dos.bodies)):
        for art_id, tile in sorted(amiga.items()):
            block = blocks.get(art_id)
            if block is None or (block.height, block.width) != (
                    tile.height, tile.width):
                tiles.append((kind, art_id, None))
                continue
            differ = 0
            for y in range(tile.height):
                for x in range(tile.width):
                    value = block.rows[y][x]
                    want = (None if value == dos_pod_icons.KEY
                            else drawn.entry[value])
                    got = tile.rows[y][x] if tile.opaque[y][x] else None
                    if want != got:
                        differ += 1
                        pairs[(kind, value, got)] += 1
            if differ:
                tiles.append((kind, art_id, differ))
            else:
                equal += 1
    return {"equal": equal, "tiles": tiles, "pairs": pairs}


def report_dos(out) -> int:
    from goldbox import dos_pod_icons
    from tools.icons import dosicons
    drawn = art()
    if drawn is None:
        out("pools-of-darkness: its disks are not all on this machine")
        return 1
    try:
        dos = dos_pod_icons.read_game(
            dosicons.game_folder("pools-of-darkness", None))
    except (OSError, ValueError, KeyError, SystemExit) as exc:
        out(f"no DOS Pools of Darkness art: {exc}")
        return 1
    found = dos_differences(drawn, dos)
    total = len(drawn.heads) + len(drawn.bodies)
    out(f"{found['equal']} of {total} tiles equal DOS's block through the "
        f"entry table")
    for kind, art_id, differ in found["tiles"]:
        out(f"  {kind} {art_id}: "
            + ("no DOS block of that size" if differ is None
               else f"{differ} pixels differ"))
    for (kind, value, got), n in sorted(found["pairs"].items()):
        out(f"  {kind}: DOS value {value} where the tile holds entry {got}: "
            f"{n} pixels")
    return 0


def report_sweep(out) -> int:
    drawn = art()
    if drawn is None:
        out("pools-of-darkness: its disks are not all on this machine")
        return 1
    problems = 0
    for record in records():
        head, body, size, colours = record.fields
        try:
            drawn.drawn(*record.fields)
        except later.LaterArtError as exc:
            out(f"{record.where} {record.name}: {exc}")
            problems += 1
            continue
        out(f"{record.where} {record.name}: head {head} body {body} size "
            f"{size} colours {colours.hex()} composes")
    return problems


def report_compose(out, name: str) -> int:
    record = find_record(name)
    if record is None:
        out(f"no Amiga Pools of Darkness character called {name}")
        return 1
    drawn = art()
    if drawn is None:
        out("pools-of-darkness: its disks are not all on this machine")
        return 1
    head, body, size, colours = record.fields
    out(f"{record.name}  {record.where}  head {head} body {body} size {size} "
        f"colours {colours.hex(' ')}")
    for label, pose in zip(("ready", "action"),
                           drawn.poses(*record.fields)):
        out(f"  {label}")
        for row in pose:
            out("    " + "".join(".." if v is None else f"{v:02x}"
                                 for v in row))
    return 0


def compare_capture(record: Record, path, drawn: later.LaterArt
                    ) -> dict[str, tuple]:
    """`{"ready": (places, fewest differing), "action": ...}` for `record`
    in the crop at `path`."""
    from tools.icons.amigaporicons import capture_pixels, find_pose
    screen = capture_pixels(path)
    ready, action = drawn.drawn(*record.fields)
    return {"ready": find_pose(screen, ready),
            "action": find_pose(screen, action)}


def report_capture(out, name: str, path, disk3=None, slot=None) -> int:
    if disk3 is not None:
        found = disk_records(AmigaDisk(pathlib.Path(disk3).read_bytes()),
                             str(disk3), slot)
        record = find_record(name, found)
    else:
        record = find_record(name)
    if record is None:
        out(f"no Amiga Pools of Darkness character called {name}")
        return 1
    try:
        drawn = art()
        if drawn is None:
            out("pools-of-darkness: its disks are not all on this machine")
            return 1
        found_places = compare_capture(record, path, drawn)
    except later.LaterArtError as exc:
        out(f"{name}: {exc}")
        return 1
    problems = 0
    for pose, (places, fewest) in found_places.items():
        if places:
            out(f"{record.name} {pose}: matches pixel for pixel at "
                + ", ".join(f"({x}, {y})" for x, y in places))
        else:
            out(f"{record.name} {pose}: no exact match; the closest differs "
                f"in {fewest} of {later.CELL * later.CELL} pixels")
            problems += 1
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--palette", action="store_true",
                        help="the recolour tables and ICON palette")
    parser.add_argument("--dos", action="store_true",
                        help="every tile against DOS's block of its id")
    parser.add_argument("--sweep", action="store_true",
                        help="compose every character on this machine")
    parser.add_argument("--compose", metavar="NAME",
                        help="a character's two poses as palette entries")
    parser.add_argument("--capture", nargs=2, metavar=("NAME", "PNG"),
                        help="find a character's poses in an ICON capture")
    parser.add_argument("--disk3", metavar="ADF",
                        help="with --capture: read the character from this "
                             "disk 3")
    parser.add_argument("--slot", metavar="L",
                        help="with --disk3: the saved game's slot letter")
    args = parser.parse_args(argv)
    if not (args.palette or args.dos or args.sweep or args.compose
            or args.capture):
        parser.error("say which: --palette, --dos, --sweep, --compose NAME "
                     "or --capture NAME PNG")
    if (args.disk3 or args.slot) and not args.capture:
        parser.error("--disk3 and --slot go with --capture")
    problems = 0
    if args.palette:
        problems += report_palette(print)
    if args.dos:
        problems += report_dos(print)
    if args.sweep:
        problems += report_sweep(print)
    if args.compose:
        problems += report_compose(print, args.compose)
    if args.capture:
        problems += report_capture(print, *args.capture, args.disk3,
                                   args.slot)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
