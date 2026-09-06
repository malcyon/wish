#!/usr/bin/env python3
"""Wait for the Windows VM's screen to stop changing, and keep the last grab.

Driving an Amiga game through `tools/amigadrive.py` is a sequence of single
keystrokes, and **a key pressed while a disk is loading is swallowed with no
sign** -- so a fixed `sleep` between steps is the thing that quietly breaks a
run.  The steps do not take a fixed time either: on one Silver Blades boot the
credits took 47 seconds, the party menu 9, and `BEGIN ADVENTURING` 56 the
first time and 129 the second.

    tools/winvmsettle.py work/331run/shots/05-loaded.png --limit 150

So this grabs `winvm shot` every couple of seconds until two consecutive grabs
are byte for byte the same, saves that one, and prints how long it took.  A
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

#: Two identical grabs is the test, so the interval is how long a screen has
#: to hold still to count as settled.  Below about a second the emulator's own
#: frame rate starts producing identical pairs mid-animation.
INTERVAL = 2.0


def settle(out: pathlib.Path, limit: float = 120.0,
           interval: float = INTERVAL) -> bool:
    """Grab until two grabs match.  True when they did inside `limit`."""
    env = dict(os.environ, SSH_ASKPASS_REQUIRE="never")
    scratch = out.with_suffix(".settling.png")
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
            if previous is not None and grab == previous:
                out.write_bytes(grab)
                print(f"settled after {time.monotonic() - started:.0f}s")
                return True
            previous = grab
            time.sleep(interval)
        if previous is not None:
            out.write_bytes(previous)
        print(f"not settled in {limit:.0f}s; kept the last grab")
        return False
    finally:
        if scratch.exists():
            scratch.unlink()


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
