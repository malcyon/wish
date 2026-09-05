#!/usr/bin/env python3
"""Photograph the automapper's party-effects row off a **running** machine.

`tools/shotstrip.py` draws the same row from an effect table it makes up,
because no save this project holds carries a party-wide effect. This one
reads the machine: the two blocks one automapper poll reads out of a booted
VICE, the `Snapshot` the automapper would build from them, and the row drawn
from that. Cast Bless in the emulator and this is the picture of what a
player is shown for it -- which is the one thing `#142 (The party effects
line is computed every poll and shown nowhere)` was never proven on.

    tools/livestrip.py --port 6521 work/issue142/bless.png

The effect table is printed as well as drawn, because a row that draws
nothing and a machine with nothing running look the same in a PNG.

**One binary-monitor client at a time.** This connects, reads and closes, so
it runs beside an idle `tools/session.py` -- but never beside `wish` or
anything else holding that socket open.

Output goes under `work/`, which is gitignored, and the tooltip is printed to
the terminal because a `grab()` does not draw one.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))

# Importing this is what forces the process offscreen and gives it a throwaway
# config directory: both run at its import time, and they have to happen
# before Qt is imported at all.
from PyQt6.QtWidgets import QApplication  # noqa: E402

from automap import live  # noqa: E402
from automap.target import ViceTarget  # noqa: E402
from tools import shotstrip  # noqa: E402


def read_snapshot(port: int, host: str = "127.0.0.1"):
    """The snapshot one automapper poll would build, and then hang up.

    Held open is what the automapper does and what this must not: a session
    driving the game needs the socket back.
    """
    target = ViceTarget(host=host, port=port)
    try:
        save0, roster = live.read_blocks(target)
    finally:
        target.close()
    return live.snapshot_from_bytes(save0, roster)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Render the automapper's party-effects row from a running "
                    "emulator's own memory.")
    ap.add_argument("out", nargs="?", default="work/livestrip.png",
                    help="where to write the PNG (default: %(default)s, "
                         "which is gitignored)")
    ap.add_argument("--port", type=int, default=6502, metavar="N",
                    help="the binary monitor to read (default: %(default)s, "
                         "the human's; a pool slot prints its own)")
    ap.add_argument("--zoom", type=int, default=4, metavar="N",
                    help="scale the picture up by this, since the icons are "
                         "13px (default: %(default)s)")
    ap.add_argument("--full", action="store_true",
                    help="keep the whole roster column rather than cropping "
                         "to the strip")
    args = ap.parse_args(argv[1:])

    snap = read_snapshot(args.port)
    if snap is None:
        print("The machine had nothing readable in it.")
        return 1
    for e in snap.effects:
        who = ("the party" if e.party_wide else
               "monsters" if e.monster else f"character {e.owner}")
        print(f"effect slot {e.slot:2d}  id {e.id:3d}  on {who}  "
              f"duration {e.duration}")
    if not snap.effects:
        print("No effect is running at all.")

    app = QApplication.instance() or QApplication(["livestrip"])
    image, tip, names = shotstrip.shoot(app, (), 0, args.zoom, args.full,
                                        snap=snap)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(out))
    print(f"Wrote {out}  ({image.width()}x{image.height()}, "
          f"zoom {args.zoom}x)")
    print(f"Icons: {', '.join(names) or 'none'}")
    print("Tooltip:")
    for line in (tip.splitlines() or ["(none)"]):
        print(f"    {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
