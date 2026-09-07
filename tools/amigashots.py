#!/usr/bin/env python3
"""Press keys at an Amiga game under WinUAE, one at a time, and photograph each.

`tools/amigadrive.py` presses a key, `tools/winvmsettle.py` waits for the
screen to stop moving, and `winvm shot` grabs the guest's whole 1920x1080
desktop with the emulator window somewhere in it.  Three calls per keystroke,
and then a person reading the result is looking at a 720x568 Amiga screen
inside a picture six times that size, most of it Windows wallpaper.

    tools/amigashots.py --holder wish3q --out work/3q/rename \\
        keys R E N A M E

Every key gets its own numbered PNG, cropped to the emulator's client area, so
a run that went wrong says which keystroke it went wrong on.  A key pressed
while a disk is loading is swallowed with no sign (`docs/182-amiga-por-in-the-
running-game.md` §7), which is the whole reason for settling between keys
rather than sleeping a fixed time.

    tools/amigashots.py crop work/3q/s01-boot.png work/3q/s01-boot-c.png

`crop` does the same to a grab somebody else took.

**Finding the emulator's screen.** WinUAE draws the Amiga into a client area
whose size is the config's own `gfx_width_windowed` x `gfx_height_windowed` --
720x568 in `tools/goldbox-a500.uae` -- and puts its status bar directly under
it, a band of the Windows control grey exactly that wide.  So the crop is
found by looking for that band rather than by remembering where the window sat
on this machine: the band names the client's left edge and its bottom, and the
config names the height.  A desktop with no such band is reported rather than
cropped to a guess, and `--at X,Y` overrides the search outright.

Nothing here opens a window on the host, and nothing here can ask a human
anything: every call goes through `winvm`, and `SSH_ASKPASS_REQUIRE` is set.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import amigadrive, winvmsettle  # noqa: E402

#: The client area `tools/goldbox-a500.uae` asks WinUAE for.  Both numbers are
#: read out of the config rather than measured off a screenshot, so a config
#: that changes them is followed by passing `--size`.
CLIENT = (720, 568)

#: Windows 11's control grey, which WinUAE's status bar is painted in.  It is
#: the one horizontal band on the desktop that is exactly the client's width.
STATUS_GREY = (240, 240, 240)

#: How far a status-bar pixel may sit from `STATUS_GREY` and still count.  A
#: grab comes back through libvirt as a lossless PNG, so this is for a theme
#: that shades the bar rather than for compression noise.
TOLERANCE = 6

#: The status bar is drawn with a raised edge above its grey face -- one row
#: of a darker grey on this build -- and that edge is part of the bar rather
#: than of the Amiga's screen.  So the search walks up off the face until a row
#: is no longer uniformly light, and this caps how far, because an Amiga screen
#: whose own bottom row happened to be pale would otherwise swallow the picture
#: a row at a time.
EDGE_ROWS = 8

#: The band of greys a row has to lie inside to read as the bar's raised edge.
#: The lower end keeps the game's own dark bottom row out; the upper end keeps
#: **white** out, and that half is what a Kickstart insert-disk screen taught:
#: it is white to the bottom of the client area, so a rule that took any light
#: row walked seven rows up into the picture and cropped seven rows of the
#: desktop in underneath.
EDGE_GREY = (200, 235)


def find_client(image, size: tuple[int, int] = CLIENT) -> tuple[int, int]:
    """The top-left of the emulator's client area, from the status bar below it.

    Raises `LookupError` when no band of the right width is found, because a
    guess here is a picture of the wrong thing that still looks like a picture.
    """
    width, height = size
    pixels = image.convert("RGB").load()
    across, down = image.size
    for y in range(height + 1, down):
        run = 0
        for x in range(across):
            r, g, b = pixels[x, y]
            near = (abs(r - STATUS_GREY[0]) <= TOLERANCE
                    and abs(g - STATUS_GREY[1]) <= TOLERANCE
                    and abs(b - STATUS_GREY[2]) <= TOLERANCE)
            run = run + 1 if near else 0
            if run == width:
                left = x - width + 1
                top = y
                for _ in range(EDGE_ROWS):
                    row = top - 1
                    if row < height:
                        break
                    if not all(EDGE_GREY[0] <= min(pixels[at, row])
                               and max(pixels[at, row]) <= EDGE_GREY[1]
                               for at in range(left, left + width)):
                        break
                    top = row
                # The bar starts on the row after the client area ends.
                return left, top - height
        # A run wider than the client is a taskbar or a titlebar, not the bar.
    raise LookupError("no WinUAE status bar of the client's width on this "
                      "desktop; pass --at X,Y")


def crop(source: pathlib.Path, out: pathlib.Path,
         at: tuple[int, int] | None = None,
         size: tuple[int, int] = CLIENT) -> tuple[int, int]:
    """Write the emulator's own screen out of a whole-desktop grab."""
    from PIL import Image

    image = Image.open(source)
    left, top = at if at is not None else find_client(image, size)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.crop((left, top, left + size[0], top + size[1])).save(out)
    return left, top


def run(holder: str, names: list[str], out: pathlib.Path, limit: float,
        at: tuple[int, int] | None, size: tuple[int, int],
        settle: float) -> int:
    """One key, one settle, one cropped PNG, for each name in turn."""
    out.mkdir(parents=True, exist_ok=True)
    for n, name in enumerate(names, 1):
        amigadrive.press(holder, name, settle)
        whole = out / f"{n:02d}-{name.lower()}.raw.png"
        if not winvmsettle.settle(whole, limit=limit):
            print(f"{n:02d} {name}: never settled in {limit:g}s", flush=True)
        shot = out / f"{n:02d}-{name.lower()}.png"
        try:
            left, top = crop(whole, shot, at, size)
        except LookupError as bad:
            print(f"{n:02d} {name}: {bad} -- kept {whole}", flush=True)
            continue
        whole.unlink()
        print(f"{n:02d} {name}: {shot} (client at {left},{top})", flush=True)
    return 0


def _point(text: str) -> tuple[int, int]:
    x, _, y = text.partition(",")
    return int(x), int(y)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", type=_point, default=None,
                        help="the client area's top-left, X,Y, instead of "
                             "searching for the status bar")
    parser.add_argument("--size", type=_point, default=CLIENT,
                        help="the client area's W,H (default 720,568, which "
                             "is what tools/goldbox-a500.uae asks for)")
    sub = parser.add_subparsers(dest="command", required=True)

    keys = sub.add_parser("keys", help="press keys, photographing each")
    keys.add_argument("--holder", required=True,
                      help="the winuae.ps1 lane claim this run holds")
    keys.add_argument("--out", required=True, type=pathlib.Path,
                      help="a directory for the numbered PNGs")
    keys.add_argument("--limit", type=float, default=90.0,
                      help="seconds to wait for the screen to settle")
    keys.add_argument("--settle", type=float, default=1.5,
                      help="seconds to wait after each key before grabbing")
    keys.add_argument("names", nargs="+",
                      help="key names, as tools/amigadrive.py spells them")

    one = sub.add_parser("crop", help="crop a grab somebody else took")
    one.add_argument("source", type=pathlib.Path)
    one.add_argument("out", type=pathlib.Path)

    args = parser.parse_args(argv)
    if args.command == "crop":
        left, top = crop(args.source, args.out, args.at, args.size)
        print(f"{args.out} (client at {left},{top})")
        return 0
    return run(args.holder, args.names, args.out, args.limit, args.at,
               args.size, args.settle)


if __name__ == "__main__":
    raise SystemExit(main())
