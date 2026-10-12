#!/usr/bin/env python3
"""Set one Amiga party member's combat-figure bytes on a copy of a save disk,
and check a capture of the game's ICON screen against the staged record.

    tools/icons/amigaiconstage.py stage --title pool --disk SAVE.adf \\
        --out STAGED.adf --slot A --member 1 --icon 7:30:2:5a413b7644ef
    tools/icons/amigaiconstage.py check --title pool --disk STAGED.adf \\
        --slot A --member 1 --capture CROP.png

`stage` reads `--disk` (or the registered image whose SHA-256 is
`--registered`), never writes it, and creates `--out`, which must not exist
yet.  In the member's record it writes `icon_head`, `icon_body`, `size` and
the six `icon_colours` bytes -- `--icon HEAD:BODY:SIZE:COLOURS` -- and
nothing else, through `tools.amiga.staging.replace_file_in_place`, then
checks that every other file and every other byte of that file is
unchanged.  Titles are `pool`, `curse`, `ssb` and `darkness`; the member is
counted from 1 in the slot's party order.  The staged disk is what
`tools/amiga/acceptance.py prepare --substitute` takes.

Editing an input and then watching the game draw from it is a valid
experiment -- the engine does not care how a byte got there -- which is what
`.claude/rules/testing.md` distinguishes from reading back a value we wrote.

`check` reads the member's figure fields off `--disk` (the staged disk, or
the one `halt` fetched), composes both poses over their boxes with the
title's composer and the player's registered art, and looks for each pose
pixel for pixel in a canonical WinUAE crop of the ICON screen.  It exits
non-zero when a pose has no exact match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from dataclasses import dataclass

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import amiga_pod, amiga_savegame, dos_port  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402

TITLES = ("pool", "curse", "ssb", "darkness")
FIELDS = ("icon_head", "icon_body", "size", "icon_colours")
COLOUR_COUNT = 6


class IconStageError(ValueError):
    """The disk, member or figure is not one this tool can stage or check."""


@dataclass(frozen=True)
class Member:
    """Where one member's record sits: its file, the record's start in the
    file and each figure field's offset in the record."""

    path: str
    data: bytes
    at: int
    offsets: dict[str, int]
    name: str

    def positions(self) -> list[int]:
        """Every byte of the file the figure fields cover."""
        out = []
        for field in FIELDS:
            width = COLOUR_COUNT if field == "icon_colours" else 1
            start = self.at + self.offsets[field]
            out += range(start, start + width)
        return out

    def fields(self) -> tuple[int, int, int, bytes]:
        """`(icon_head, icon_body, size, icon_colours)` as the file holds them."""
        def at(field: str) -> int:
            return self.at + self.offsets[field]
        colours = at("icon_colours")
        return (self.data[at("icon_head")], self.data[at("icon_body")],
                self.data[at("size")],
                bytes(self.data[colours:colours + COLOUR_COUNT]))


def parse_icon(text: str) -> tuple[int, int, int, bytes]:
    """`HEAD:BODY:SIZE:COLOURS`, the colours as twelve hex digits."""
    parts = text.split(":")
    if len(parts) != 4 or not all(p.isdigit() for p in parts[:3]):
        raise IconStageError(f"--icon {text!r} is not HEAD:BODY:SIZE:COLOURS")
    head, body, size = (int(p) for p in parts[:3])
    try:
        colours = bytes.fromhex(parts[3])
    except ValueError:
        colours = b""
    if len(colours) != COLOUR_COUNT:
        raise IconStageError(f"--icon colours {parts[3]!r} are not "
                             f"{2 * COLOUR_COUNT} hex digits")
    if not 0 <= head <= 13 or not 0 <= body <= 31 or size not in (1, 2):
        raise IconStageError(f"--icon {text!r}: head is 0 to 13, body 0 to "
                             f"31 and size 1 or 2")
    return head, body, size, colours


def _pool(disk: AmigaDisk, slot: str, member: int) -> Member:
    from goldbox import amiga_por
    try:
        drawer = amiga_savegame.por_save_drawer(disk)
    except amiga_savegame.AmigaSaveError:
        drawer = ""
    count = len(amiga_savegame.read_por_characters(disk, slot, drawer))
    _in_party(slot, member, count)
    path = amiga_savegame.por_save_path(
        amiga_por.por_filename(slot.upper(), member, ".sav"), drawer)
    data = disk.read_file(path)
    offsets = {f: amiga_por.amiga_por_offset(dos_port.FIELDS_BY_NAME[f].offset)
               for f in FIELDS}
    return Member(path, data, 0, offsets,
                  amiga_por.por_character(data, b"", b"").name.strip())


def _later(disk: AmigaDisk, slot: str, member: int, title: str) -> Member:
    container = (amiga_savegame.CURSE if title == "curse"
                 else amiga_savegame.SILVER_BLADES)
    path = amiga_savegame.slot_path(container, slot)
    data = disk.read_file(path)
    save = amiga_savegame.parse(data, container, path)
    _in_party(slot, member, len(save.blocks))
    deltas = container.deltas
    offsets = {f: deltas.offset(deltas.dos_field(f).offset) for f in FIELDS}
    return Member(path, data, save.blocks[member - 1][0], offsets,
                  save.characters[member - 1].name.strip())


def _darkness(disk: AmigaDisk, slot: str, member: int) -> Member:
    path = amiga_savegame.pod_slot_path(slot)
    data = amiga_savegame.pod_read_slot(disk, slot)
    blocks = amiga_savegame.pod_parse(data).characters
    _in_party(slot, member, len(blocks))
    offsets = {"icon_head": amiga_pod.ICON_HEAD,
               "icon_body": amiga_pod.ICON_BODY, "size": amiga_pod.SIZE,
               "icon_colours": amiga_pod.ICON_COLOURS}
    return Member(path, data, blocks[member - 1].at, offsets,
                  blocks[member - 1].name.strip())


def _in_party(slot: str, member: int, count: int) -> None:
    if not 1 <= member <= count:
        raise IconStageError(f"slot {slot.upper()} has members 1 to {count}, "
                             f"not {member}")


def locate(disk: AmigaDisk, title: str, slot: str, member: int) -> Member:
    """Member `member` (1 first) of slot `slot` of `title` on `disk`."""
    try:
        if title == "pool":
            return _pool(disk, slot, member)
        if title in ("curse", "ssb"):
            return _later(disk, slot, member, title)
        if title == "darkness":
            return _darkness(disk, slot, member)
    except (AmigaDiskError, amiga_savegame.AmigaSaveError,
            amiga_savegame.PodSaveError) as exc:
        raise IconStageError(f"slot {slot.upper()}: {exc}") from exc
    raise IconStageError(f"the title is one of {', '.join(TITLES)}, "
                         f"not {title!r}")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage(source: bytes, title: str, slot: str, member: int,
          icon: tuple[int, int, int, bytes]) -> tuple[bytes, dict]:
    """`(staged image, report)`: `source` with the member's figure fields
    set to `icon` and nothing else changed.  `source` is not modified."""
    from tools.amiga import staging
    disk = AmigaDisk(bytearray(source))
    found = locate(disk, title, slot, member)
    head, body, size, colours = icon
    record = bytearray(found.data)
    for field, value in (("icon_head", head), ("icon_body", body),
                         ("size", size)):
        record[found.at + found.offsets[field]] = value
    start = found.at + found.offsets["icon_colours"]
    record[start:start + COLOUR_COUNT] = colours
    try:
        staging.replace_file_in_place(disk, found.path, bytes(record))
    except staging.StageError as exc:
        raise IconStageError(str(exc)) from exc
    staged = disk.to_bytes()
    check_staged(source, staged, title, slot, member, icon)
    before = found.fields()
    return staged, {
        "title": title, "slot": slot.upper(), "member": member,
        "name": found.name, "file": found.path,
        "before": _fields_json(before), "after": _fields_json(icon),
        "source_sha256": _sha(source), "staged_sha256": _sha(staged),
        "file_sha256_before": _sha(found.data),
        "file_sha256_after": _sha(bytes(record))}


def _fields_json(fields) -> dict:
    head, body, size, colours = fields
    return {"icon_head": head, "icon_body": body, "size": size,
            "icon_colours": bytes(colours).hex()}


def check_staged(source: bytes, staged: bytes, title: str, slot: str,
                 member: int, icon: tuple[int, int, int, bytes]) -> None:
    """Block a staged image that is not `source` with `icon` written into
    the member's figure fields and nothing else."""
    before, after = AmigaDisk(bytearray(source)), AmigaDisk(bytearray(staged))
    problems = after.verify()
    if problems:
        raise IconStageError(f"the staged disk fails verification: "
                             f"{problems}")
    old, new = (locate(d, title, slot, member) for d in (before, after))
    if new.fields() != tuple(icon):
        raise IconStageError("the staged record does not read back the "
                             "figure it was given")
    files = {p: e for p, e in before.walk() if not e.is_dir}
    if {p for p, e in after.walk() if not e.is_dir} != set(files):
        raise IconStageError("the staged disk holds other files")
    allowed = set(old.positions())
    # AmigaDOS compares names without case, and the readers spell a drawer
    # as the title's own code does, not as the disk does.
    for path in files:
        was, now = before.read_file(path), after.read_file(path)
        if path.upper() != old.path.upper() and was != now:
            raise IconStageError(f"{path} changed")
        if len(was) != len(now) or any(
                a != b and i not in allowed
                for i, (a, b) in enumerate(zip(was, now))):
            raise IconStageError(f"{path} changed outside the figure fields")


def stage_file(source: pathlib.Path | None, registered: str | None,
               out: pathlib.Path, title: str, slot: str, member: int,
               icon: tuple[int, int, int, bytes]) -> dict:
    """:func:`stage` from a file or a registered image, written to `out`,
    which must not exist; the report gains both paths."""
    if (source is None) == (registered is None):
        raise IconStageError("give one of --disk and --registered")
    if source is not None:
        data, label = pathlib.Path(source).read_bytes(), str(source)
    else:
        data, label = registered_image(registered)
    staged, report = stage(data, title, slot, member, icon)
    with open(out, "xb") as handle:
        handle.write(staged)
    report["source"], report["out"] = label, str(out)
    return report


def registered_image(sha256: str) -> tuple[bytes, str]:
    """`(bytes, label)` of the registered Amiga image with this SHA-256."""
    from tools.amiga import amigasaves
    for label, data in amigasaves.images():
        if _sha(data) == sha256.lower():
            return data, label
    raise IconStageError(f"no registered Amiga image has SHA-256 {sha256}")


# -- check ------------------------------------------------------------------------
def figure(title: str, fields: tuple[int, int, int, bytes]):
    """Both poses over their boxes as rows of `(r, g, b)`, drawn with the
    title's composer from the player's registered art; None when the art is
    not all on this machine."""
    head, body, size, colours = fields
    if title == "pool":
        from goldbox import amiga_por_icons as art
        from tools.icons import amigaporicons
        drawn, code = amigaporicons.amiga_art(), amigaporicons.program()
        if drawn is None or code is None:
            return None
        palette = art.icon_palette(code)
        frame = drawn["frame"][art.FRAME_BLOCK]
        return tuple(tuple(tuple(palette[v] for v in row)
                           for row in art.on_frame(frame, pose))
                     for pose in art.compose(drawn["head"], drawn["body"],
                                             head, body, size, colours))
    if title in ("curse", "ssb"):
        from tools.icons import amigalatericons
        drawn = amigalatericons.title_art(
            "curse-of-the-azure-bonds" if title == "curse"
            else "secret-of-the-silver-blades")
    else:
        from tools.icons import amigapodicons
        drawn = amigapodicons.art()
    return None if drawn is None else drawn.drawn(head, body, size, colours)


def check(disk: AmigaDisk, title: str, slot: str, member: int,
          capture: pathlib.Path, out=print) -> int:
    """How many of the two poses have no exact match in `capture`."""
    from tools.icons.amigaporicons import capture_pixels, find_pose
    found = locate(disk, title, slot, member)
    fields = found.fields()
    out(f"{found.name}: head {fields[0]} body {fields[1]} size {fields[2]} "
        f"colours {fields[3].hex()}")
    poses = figure(title, fields)
    if poses is None:
        out(f"{title}: its art is not all on this machine")
        return 1
    screen = capture_pixels(capture)
    problems = 0
    for label, pose in zip(("ready", "action"), poses):
        places, fewest = find_pose(screen, pose)
        if places:
            out(f"{found.name} {label}: matches pixel for pixel at "
                + ", ".join(f"({x}, {y})" for x, y in places))
        else:
            out(f"{found.name} {label}: no exact match; the closest differs "
                f"in {fewest} of {len(pose) * len(pose[0])} pixels")
            problems += 1
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("stage", "check"):
        p = sub.add_parser(name)
        p.add_argument("--title", choices=TITLES, required=True)
        p.add_argument("--slot", required=True, help="the save slot letter")
        p.add_argument("--member", type=int, required=True,
                       help="the member, 1 for the party's first")
        p.add_argument("--disk", type=pathlib.Path,
                       help="the save disk image to read")
        if name == "stage":
            p.add_argument("--registered", metavar="SHA256",
                           help="read the registered image with this hash "
                                "instead of --disk")
            p.add_argument("--out", type=pathlib.Path, required=True,
                           help="the staged image to create")
            p.add_argument("--icon", required=True,
                           metavar="HEAD:BODY:SIZE:COLOURS")
        else:
            p.add_argument("--capture", type=pathlib.Path, required=True,
                           help="a canonical crop of the ICON screen")
    args = parser.parse_args(argv)
    try:
        if args.command == "stage":
            report = stage_file(args.disk, args.registered, args.out,
                                args.title, args.slot, args.member,
                                parse_icon(args.icon))
            print(json.dumps(report, indent=2))
            return 0
        if args.disk is None:
            raise IconStageError("check needs --disk")
        return 1 if check(AmigaDisk(bytearray(args.disk.read_bytes())),
                          args.title, args.slot, args.member,
                          args.capture) else 0
    except (IconStageError, OSError) as exc:
        print(f"amigaiconstage: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
