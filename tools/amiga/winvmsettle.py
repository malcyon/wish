#!/usr/bin/env python3
"""Wait for the Windows VM's screen to stop changing, and keep the last grab.

Driving an Amiga game through `tools/amiga/amigadrive.py` is a sequence of single
keystrokes, and **a key pressed while a disk is loading is swallowed with no
sign** -- so a fixed `sleep` between steps is the thing that quietly breaks a
run.  The steps do not take a fixed time either: on one Silver Blades boot the
credits took 47 seconds, the party menu 9, and `BEGIN ADVENTURING` 56 the
first time and 129 the second.

    tools/amiga/winvmsettle.py 05-loaded.png --limit 150

So this grabs `winvm shot` every couple of seconds until two consecutive grabs
show the same emulator screen, saves that one, and prints how long it took.  A
run that never settles inside `--limit` keeps the last grab and says so rather
than pretending: a screen that is still animating is worth photographing even
when it cannot be waited out.

Nothing here opens a window on the host -- `winvm shot` takes the guest's
screen through libvirt -- and nothing here can ask a human anything, because
`SSH_ASKPASS_REQUIRE` is set on every call.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

#: Two identical grabs is the test, so the interval is how long a screen has
#: to hold still to count as settled.  Below about a second the emulator's own
#: frame rate starts producing identical pairs mid-animation.
INTERVAL = 2.0


def _frame(grab: pathlib.Path, cropped: pathlib.Path) -> bytes:
    """What two grabs are compared by: the emulator's screen, else the desktop.

    The taskbar clock and any console beside the window change every minute
    without the game moving, so comparing whole grabs never settles.
    """
    # Imported here because amigashots imports this module.
    from tools.amiga import amigashots

    try:
        amigashots.crop(grab, cropped)
    except (LookupError, OSError):
        # No WinUAE window yet, or a grab that is not an image: the whole grab
        # is all there is to compare.
        return grab.read_bytes()
    return cropped.read_bytes()


def settle(out: pathlib.Path, limit: float = 120.0,
           interval: float = INTERVAL) -> bool:
    """Grab until two grabs match.  True when they did inside `limit`."""
    env = dict(os.environ, SSH_ASKPASS_REQUIRE="never")
    scratch = out.with_suffix(".settling.png")
    cropped = out.with_suffix(".settling-crop.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    previous, started = None, time.monotonic()
    try:
        while time.monotonic() - started < limit:
            grab = subprocess.run(["winvm", "shot", str(scratch)],
                                  capture_output=True, text=True, env=env)
            if grab.returncode != 0:
                # A shut-off VM is the usual reason, and libvirt says so in
                # one line. A traceback here reads as a bug in this file.
                raise SystemExit(
                    "winvm shot failed, so there is no screen to wait for: "
                    + (grab.stderr or grab.stdout).strip())
            grab = scratch.read_bytes()
            frame = _frame(scratch, cropped)
            if previous is not None and frame == previous[0]:
                out.write_bytes(grab)
                print(f"settled after {time.monotonic() - started:.0f}s")
                return True
            previous = (frame, grab)
            time.sleep(interval)
        if previous is not None:
            out.write_bytes(previous[1])
        print(f"not settled in {limit:.0f}s; kept the last grab")
        return False
    finally:
        for leftover in (scratch, cropped):
            if leftover.exists():
                leftover.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse
                                     .RawDescriptionHelpFormatter)
    parser.add_argument("path", help="where to save the settled screen")
    parser.add_argument("--limit", type=float, default=120.0,
                        help="seconds to wait before giving up (default 120)")
    parser.add_argument("--interval", type=float, default=INTERVAL,
                        help=f"seconds between grabs (default {INTERVAL})")
    args = parser.parse_args(argv)
    return 0 if settle(pathlib.Path(args.path), args.limit,
                       args.interval) else 1


if __name__ == "__main__":
    sys.exit(main())
