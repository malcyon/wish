#!/usr/bin/env python3
"""Compose DOS combat figures and re-read the ICON screen's rules from code.

`goldbox/dos_icons.py` composes a Pool of Radiance, Curse or Silver Blades
figure from the title's `CHEAD.DAX` and `CBODY.DAX`.  This prints what it
composes, and re-takes every reading the module rests on from the player's
own `GAME.OVR` and `START.EXE`.

``--art``
    Each title's blocks: how many heads, bodies and ICON-screen box poses
    decode, and how many head blocks draw the same picture in both poses.

``--palette``
    Each title's code readings against `goldbox.dos_icons`: the recolour part
    table in `START.EXE`'s data segment, whether the figure loader ORs the head
    into the body, whether the ICON routine exchanges palette registers 0 and
    8, the loader's fixed remap of value 8, and which box pose sits behind the
    action pose.  Then the sixteen ICON-screen colours.  Exits 1 when a reading
    disagrees with the module.

``--compose NAME``
    NAME's record from `--save` (default the game folder's `SAVE`), slot
    `--slot`: its icon fields and both poses over their boxes, one hex digit a
    palette index.

``--capture NAME PNG``
    NAME's two poses drawn over their boxes in the ICON palette, looked for in
    PNG, a 320x200 frame or a 640x400 one with every pixel doubled.  Prints
    where each pose matches pixel for pixel, or the fewest pixels any place
    differs by, and the place `goldbox.dos_icons.PLACES` expects for `NEW`.

    tools/icons/dosicons.py --art --palette
    tools/icons/dosicons.py --title pool --game /mnt/disks/por-dos-play --compose BRUTUS
    tools/icons/dosicons.py --title pool --game DIR --capture BRUTUS icon.png

Game folders are `--game`, else the archives' (`$FR_ARCHIVES`, then
`gamedisks.yaml`).  Everything is opened read-only and nothing is written.
The write-up is `docs/168-dos-dax-and-combat-icons.md`, "The ICON screen".
"""

from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import dos_codec, exepack  # noqa: E402
from goldbox import dos_icons as art  # noqa: E402
from tools.dos import dosovrmap  # noqa: E402
from tools.icons import dosicontitles  # noqa: E402

#: Short names on the command line, to the module's title keys.
TITLES = {"pool": "pool-of-radiance", "curse": "curse-of-the-azure-bonds",
          "ssb": "secret-of-the-silver-blades"}

#: Where each title's recolour builder reads its part table, in `START.EXE`'s
#: data segment; `part_table` checks the builder reads it there.
PART_TABLE_AT = {"pool-of-radiance": 0x3CF5,
                 "curse-of-the-azure-bonds": 0x3EC2,
                 "secret-of-the-silver-blades": 0x4CAF}

#: The ICON menu's closing question, a string just before the routine.
ICON_QUESTION = b"Is this icon ok?"
PROLOGUE = b"\x55\x89\xe5"
#: `mov al, 0; push ax; mov al, 8; push ax; lcall` then the same with 8 and 0:
#: palette register 0 set to colour 8 and register 8 to colour 0.
SWAP = re.compile(rb"\xb0\x00\x50\xb0\x08\x50\x9a....\xb0\x08\x50\xb0\x00\x50"
                  rb"\x9a", re.S)
EMPTY_ROUTINE = b"\x55\x89\xe5\x89\xec\x5d\xcb"
#: The figure loader's record-colour step: `and al, 0Fh` ... `mov al,
#: [di+table]`, which names the part table's data-segment offset.
PART_LOOKUP = re.compile(rb"\x24\x0f\x8a\xd0\x8a\x46\xdc\x30\xe4\x8b\xf8"
                         rb"\x8a\x85(..)", re.S)
#: `mov di, src; push ds; push di; mov di, dst; push ds; push di; xor ax,
#: ax; push ax; mov al, 0; push ax`: a remap through two data-segment tables.
FIXED_REMAP = re.compile(rb"\xbf(..)\x1e\x57\xbf(..)\x1e\x57\x31\xc0\x50"
                         rb"\xb0\x00\x50", re.S)
#: The ICON draw helper's second box: `add ax, 3; push ax; mov al, [bp+8];
#: push ax; mov al, 0; push ax; mov al, POSE; push ax; mov al, 25; push ax`.
ACTION_BOX = re.compile(rb"\x05\x03\x00\x50\x8a\x46\x08\x50\xb0\x00\x50"
                        rb"\xb0(.)\x50\xb0\x19\x50", re.S)


class CaptureError(ValueError):
    """A capture this tool cannot read pixel for pixel."""


# -- where the games are -------------------------------------------------------
def game_folder(title: str, given: str | None) -> pathlib.Path:
    """`--game`, else the archives' folder for `title`."""
    if given:
        return pathlib.Path(given).expanduser()
    root = dosicontitles.archives(None)
    return dosicontitles.find_folders(root, [title])[title]


def _file(folder: pathlib.Path, name: str) -> bytes:
    for path in folder.iterdir():
        if path.name.upper() == name:
            return path.read_bytes()
    raise SystemExit(f"{folder} holds no {name}")


# -- code readings ---------------------------------------------------------------
def data_segment(image: bytes, info: dict) -> int:
    """The paragraph Turbo Pascal's System unit loads into DS at start-up.

    The entry's first instruction is a far call to the System unit's
    initialisation, which opens with `mov dx, imm16; mov ds, dx`.
    """
    entry = info["real_cs"] * 16 + info["real_ip"]
    if image[entry] != 0x9A:
        raise ValueError("START.EXE does not open with a far call")
    off, seg = struct.unpack_from("<HH", image, entry + 1)
    init = seg * 16 + off
    if image[init] != 0xBA or image[init + 3:init + 5] != b"\x8e\xda":
        raise ValueError("the System unit does not set DS the way it is read")
    return struct.unpack_from("<H", image, init + 1)[0]


def loader(ovr: bytes) -> tuple[int, int]:
    """`(start, end)` of the figure loader: the routine after the
    `CHEAD`/`CBODY` string pair, to its first `retf 2`."""
    at = ovr.find(b"\x05CHEAD\x05CBODY")
    if at < 0:
        raise ValueError("no CHEAD/CBODY string pair in GAME.OVR")
    start = ovr.find(PROLOGUE, at)
    end = ovr.find(b"\xca\x02\x00", start)
    return start, end + 3


def near_targets(ovr: bytes, start: int, end: int) -> list[int]:
    """Targets of `push cs; call rel16` between `start` and `end`."""
    out = []
    for m in re.finditer(rb"\x0e\xe8(..)", ovr[start:end], re.S):
        at = start + m.start() + 1
        out.append(at + 3 + struct.unpack("<h", m.group(1))[0])
    return out


def readings(game: pathlib.Path) -> dict:
    """Everything `--palette` reports for one game folder."""
    ovr = _file(game, "GAME.OVR")
    image, info = exepack.unpack(_file(game, "START.EXE"))
    ds = data_segment(image, info) * 16
    start, end = loader(ovr)
    body = ovr[start:end]
    tables = sorted({struct.unpack("<H", m.group(1))[0]
                     for m in PART_LOOKUP.finditer(body)})
    composite = []
    for target in near_targets(ovr, start, end):
        routine = ovr[target:ovr.find(b"\xca\x08\x00", target) + 3]
        composite.append({"at": target,
                          "or": b"\x0a\xc2\x8a\xd0" in routine,
                          "and_mask": b"\x22\xc2\x8a\xd0" in routine})
    remaps = []
    for m in FIXED_REMAP.finditer(body):
        src, dst = (struct.unpack("<H", g)[0] for g in m.groups())
        a, b = image[ds + src:ds + src + 16], image[ds + dst:ds + dst + 16]
        remaps.append({"at": start + m.start(), "src": src, "dst": dst,
                       "changes": {i: b[j] for j, i in enumerate(a)
                                   if a[j] != b[j]}})
    swap = icon_swap(ovr, image)
    boxes = sorted({m.group(1)[0] for m in ACTION_BOX.finditer(ovr)})
    return {"ds": ds // 16, "part_tables": {t: image[ds + t:ds + t + 7]
                                            for t in tables},
            "loader": (start, end), "composite": composite,
            "remaps": remaps, "swap": swap, "action_boxes": boxes}


def icon_swap(ovr: bytes, image: bytes) -> dict:
    """What the ICON routine's first far calls do to the palette.

    `routine` is the ICON routine's offset; `calls` the `GAME.OVR` offsets of
    the overlay entries it calls in its first 0x40 bytes; `swap` the one that
    sets register 0 to 8 and 8 to 0, `empty` those that do nothing.
    """
    at = ovr.find(ICON_QUESTION)
    if at < 0:
        raise ValueError("no 'Is this icon ok?' in GAME.OVR")
    routine = ovr.find(PROLOGUE, at)
    units = dosovrmap.units(image, len(ovr))
    calls, swap, empty = [], None, []
    for m in re.finditer(rb"\x9a(..)(..)", ovr[routine:routine + 0x40], re.S):
        off, seg = (struct.unpack("<H", g)[0] for g in m.groups())
        where, target = dosovrmap.resolve(units, seg, off)
        if where != "GAME.OVR" or target is None:
            continue
        calls.append(target)
        if ovr[target:target + len(EMPTY_ROUTINE)] == EMPTY_ROUTINE:
            empty.append(target)
        elif SWAP.search(ovr[target:ovr.find(b"\xcb", target + 0x18) + 1]):
            swap = target
    return {"routine": routine, "calls": calls, "swap": swap, "empty": empty}


def check(title: str, found: dict) -> list[str]:
    """Each way `found` disagrees with `goldbox.dos_icons`; empty if none."""
    screen = art.ICON_SCREENS[title]
    problems = []
    tables = found["part_tables"]
    if list(tables) != [PART_TABLE_AT[title]]:
        problems.append(f"part table read at {[hex(t) for t in tables]}, "
                        f"not {PART_TABLE_AT[title]:#x}")
    for t, raw in tables.items():
        if tuple(raw[1:]) != art.PART_TABLE:
            problems.append(f"part table at ds:{t:#x} is {raw.hex()}")
    if len(found["composite"]) != 2 or not all(
            c["or"] and c["and_mask"] for c in found["composite"]):
        problems.append(f"composite is not OR-and-mask twice: "
                        f"{found['composite']}")
    outline = any(r["changes"] == {8: 0} for r in found["remaps"])
    if outline != screen.outline_to_black:
        problems.append(f"remaps {found['remaps']} against outline_to_black "
                        f"{screen.outline_to_black}")
    if (found["swap"]["swap"] is not None) != screen.swaps_black_and_grey:
        problems.append(f"ICON palette calls {found['swap']} against "
                        f"swaps_black_and_grey {screen.swaps_black_and_grey}")
    if found["action_boxes"] != [screen.action_box]:
        problems.append(f"action box poses {found['action_boxes']}, not "
                        f"[{screen.action_box}]")
    return problems


# -- the figures -------------------------------------------------------------------
def find_record(save: pathlib.Path, slot: str, name: str):
    """The `CHRDAT<slot><n>.SAV` record named `name` (any case)."""
    for path in sorted(save.glob(f"CHRDAT{slot}?.SAV")):
        char = dos_codec.read_character(path)
        if char.name.strip().upper() == name.strip().upper():
            return char
    raise SystemExit(f"no character called {name} in {save} slot {slot}")


def drawn(game_art: art.GameArt, char, title: str):
    """`(ready, action)` as palette indices over their boxes."""
    poses = art.compose(game_art.heads, game_art.bodies,
                        char.get("icon_head"), char.get("icon_body"),
                        char.get("size"), bytes(char.get("icon_colours")),
                        title)
    return tuple(art.on_frame(art.frame_for(game_art, n, title), pose)
                 for n, pose in enumerate(poses))


def capture_pixels(path):
    """A frame's 320x200 pixels as packed RGB, undoubling a 640x400 one.

    Raises :class:`CaptureError` for any other size, or a doubled frame
    whose 2x2 blocks are not each one colour.
    """
    import numpy
    from PIL import Image
    with Image.open(path) as image:
        rgb = numpy.asarray(image.convert("RGB"), dtype=numpy.int32)
    packed = rgb[..., 0] << 16 | rgb[..., 1] << 8 | rgb[..., 2]
    if packed.shape == (200, 320):
        return packed
    if packed.shape != (400, 640):
        raise CaptureError(f"{path}: {packed.shape[1]}x{packed.shape[0]} is "
                           f"neither 320x200 nor 640x400")
    small = packed[::2, ::2]
    for dy in (0, 1):
        for dx in (0, 1):
            if not numpy.array_equal(packed[dy::2, dx::2], small):
                raise CaptureError(f"{path}: not every pixel is a "
                                   f"single-colour 2x2 block")
    return small


def find_pose(screen, pose) -> tuple[list[tuple[int, int]], int]:
    """`(places matching pixel for pixel, fewest pixels differing anywhere)`,
    with `pose` as rows of `(r, g, b)`; places are top-left `(x, y)`."""
    import numpy
    from numpy.lib.stride_tricks import sliding_window_view
    want = numpy.array([[r << 16 | g << 8 | b for r, g, b in row]
                        for row in pose], dtype=numpy.int32)
    if want.shape[0] > screen.shape[0] or want.shape[1] > screen.shape[1]:
        raise CaptureError("the pose is larger than the frame")
    differ = (sliding_window_view(screen, want.shape) != want).sum(
        axis=(2, 3))
    ys, xs = numpy.nonzero(differ == 0)
    return sorted(zip(xs.tolist(), ys.tolist())), int(differ.min())


# -- reports -----------------------------------------------------------------------
def report_art(out, folders) -> int:
    for title, game in folders.items():
        g = art.read_game(game)
        same = sum(g.heads[h].rows == g.heads[h + art.ACTION].rows
                   for h in g.heads if h < art.ACTION
                   and h + art.ACTION in g.heads)
        out(f"{title}: {len(g.heads)} head blocks, {len(g.bodies)} body "
            f"blocks, box blocks {art.FRAME_BLOCK} and "
            f"{art.FRAME_BLOCK + art.ACTION}; {same} heads draw the same "
            f"picture in both poses")
    return 0


def report_palette(out, folders) -> int:
    problems = 0
    for title, game in folders.items():
        found = readings(game)
        out(f"{title}  ({game})")
        out(f"  data segment {found['ds']:#06x}; figure loader "
            f"{found['loader'][0]:#x}-{found['loader'][1]:#x}")
        for t, raw in found["part_tables"].items():
            out(f"  part table ds:{t:#06x} = {raw.hex(' ')}")
        for c in found["composite"]:
            out(f"  composite {c['at']:#x}: OR {c['or']}, mask AND "
                f"{c['and_mask']}")
        for r in found["remaps"]:
            out(f"  fixed remap at {r['at']:#x}: ds:{r['src']:#x} -> "
                f"ds:{r['dst']:#x} changes {r['changes']}")
        s = found["swap"]
        out(f"  ICON routine {s['routine']:#x} calls "
            f"{[hex(c) for c in s['calls']]}; register 0/8 exchange "
            f"{hex(s['swap']) if s['swap'] is not None else 'none'}; empty "
            f"{[hex(e) for e in s['empty']]}")
        out(f"  action box pose {found['action_boxes']}")
        palette = art.icon_palette(title)
        out("  palette " + " ".join(f"{i:x}=#{r:02X}{g:02X}{b:02X}"
                                    for i, (r, g, b) in enumerate(palette)))
        for problem in check(title, found):
            out(f"  DISAGREES: {problem}")
            problems += 1
    return problems


def report_compose(out, title, game, save, slot, name) -> int:
    char = find_record(save, slot, name)
    out(f"{char.name.strip()}: head {char.get('icon_head')}, body "
        f"{char.get('icon_body')}, size {char.get('size')}, colours "
        f"{bytes(char.get('icon_colours')).hex(' ')}")
    ready, action = drawn(art.read_game(game), char, title)
    for a, b in zip(ready, action):
        out("".join(f"{v:x}" for v in a) + "   "
            + "".join(f"{v:x}" for v in b))
    return 0


def report_capture(out, title, game, save, slot, name, path) -> int:
    try:
        screen = capture_pixels(path)
    except CaptureError as exc:
        out(str(exc))
        return 1
    palette = art.icon_palette(title)
    poses = drawn(art.read_game(game), find_record(save, slot, name), title)
    problems = 0
    for n, (label, pose) in enumerate(zip(("ready", "action"), poses)):
        rgb = [[palette[v] for v in row] for row in pose]
        places, fewest = find_pose(screen, rgb)
        expected = art.PLACES[("new", n)]
        if places:
            out(f"{name} {label}: pixel for pixel at "
                + ", ".join(f"({x}, {y})" for x, y in places)
                + f"; NEW expected at {expected}")
        else:
            out(f"{name} {label}: nowhere; the closest place differs in "
                f"{fewest} of {art.CELL * art.CELL} pixels")
            problems += 1
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--title", choices=sorted(TITLES),
                        help="one title; --art and --palette default to all "
                             "three")
    parser.add_argument("--game", help="the title's DOS game folder")
    parser.add_argument("--save", help="the save folder (default GAME/SAVE)")
    parser.add_argument("--slot", default="A", help="the save slot letter")
    parser.add_argument("--art", action="store_true",
                        help="each title's figure blocks")
    parser.add_argument("--palette", action="store_true",
                        help="the code readings and the ICON colours")
    parser.add_argument("--compose", metavar="NAME",
                        help="NAME's two poses as palette indices")
    parser.add_argument("--capture", nargs=2, metavar=("NAME", "PNG"),
                        help="NAME's composed figure against an ICON frame")
    args = parser.parse_args(argv)
    if not (args.art or args.palette or args.compose or args.capture):
        parser.error("say which: --art, --palette, --compose or --capture")
    if args.game and not args.title:
        parser.error("--game needs --title")
    keys = [TITLES[args.title]] if args.title else list(TITLES.values())
    folders = {k: game_folder(k, args.game) for k in keys}
    problems = 0
    if args.art:
        problems += report_art(print, folders)
    if args.palette:
        problems += report_palette(print, folders)
    if args.compose or args.capture:
        if not args.title:
            parser.error("--compose and --capture need --title")
        title = keys[0]
        game = folders[title]
        save = pathlib.Path(args.save) if args.save else game / "SAVE"
        if args.compose:
            problems += report_compose(print, title, game, save, args.slot,
                                       args.compose)
        if args.capture:
            problems += report_capture(print, title, game, save, args.slot,
                                       *args.capture)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
